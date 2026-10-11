'use strict';
const CLIENT_ID = process.argv[2]; // Public App Client ID only; owner passes locally. Never pass tokens on command line.
const CANARY = 'kinoko34077/kinotch-default-canary';
const REPO_ID = 1384948130;
const USER_ID = 79015263;
const EXPECTED_SLUG = 'kinotch-c3b-meta-proof';
const API = 'https://api.github.com';
let apiCalls=0, token=null, results={};
const MAX_API=12, pause=(ms)=>new Promise(r=>setTimeout(r,ms));
const print=(name,body)=>console.log(name+' '+JSON.stringify(body));
function stop(reason){print('HALT',{reason,apiCalls});process.exitCode=2;throw new Error('__HALT__')}
async function limitedJson(r,limit,oversizeReason){
 const reader=r.body?.getReader();if(!reader)return null;
 const chunks=[];let size=0;
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
  if(size>limit){await reader.cancel();stop(oversizeReason)}chunks.push(Buffer.from(value));}
 try{return JSON.parse(Buffer.concat(chunks).toString('utf8'))}catch{return null}
}
async function oauth(path,body){
 if(path!=='/login/device/code'&&path!=='/login/oauth/access_token')stop('BAD_OAUTH_ENDPOINT');
 const r=await fetch('https://github.com'+path,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(body),redirect:'manual',signal:AbortSignal.timeout(15000)});
 if(r.status!==200)stop('OAUTH_HTTP_'+r.status);
 const data=await limitedJson(r,65536,'OVERSIZED_OAUTH_RESPONSE');
 if(!data||typeof data!=='object'||Array.isArray(data))stop('INVALID_OAUTH_RESPONSE');
 return data;
}
async function call(url,opt={}){
 if(++apiCalls>MAX_API)stop('API_BUDGET');
 const fixed = new Set([API+'/user', API+'/user/installations?per_page=100',API+'/repos/'+CANARY,API+'/repos/'+CANARY+'/branches/main',API+'/graphql']);
 const installationRepos = /^https:\/\/api\.github\.com\/user\/installations\/[1-9][0-9]*\/repositories\?per_page=100$/;
 if(!fixed.has(url)&&!installationRepos.test(url))stop('BAD_API_ENDPOINT');
 const method=opt.method||'GET';
 if((url===API+'/graphql') !== (method==='POST'))stop('BAD_API_METHOD');
 const r=await fetch(url,{method:opt.method||'GET',headers:{'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Authorization':'Bearer '+token,...(opt.body?{'Content-Type':'application/json'}:{})},body:opt.body?JSON.stringify(opt.body):undefined,redirect:'manual',signal:AbortSignal.timeout(15000)});
 const d=await limitedJson(r,262144,'OVERSIZED_API_RESPONSE');
 return {status:r.status,data:d,redirect:r.status>=300&&r.status<400,acceptedPermissions:r.headers.get('x-accepted-github-permissions')};
}
async function graphql(query){return await call(API+'/graphql',{method:'POST',body:{query}})}
const HEAD_QUERY='query { repository(owner:"kinoko34077",name:"kinotch-default-canary") { databaseId nameWithOwner isPrivate defaultBranchRef { name target { oid } } } }';
const BLOB_QUERY='query { repository(owner:"kinoko34077",name:"kinotch-default-canary") { object(expression:"HEAD:README.md") { ... on Blob { byteSize } } } }';
function hasError(v){
 if(v.status!==200||v.redirect||!v.data||typeof v.data!=='object'||Array.isArray(v.data))return true;
 if(Object.hasOwn(v.data,'errors')&&(!Array.isArray(v.data.errors)||v.data.errors.length>0))return true;
 return false;
}
async function test(){
 const u=await call(API+'/user');
 if(u.status!==200||u.data?.id!==USER_ID||u.data?.login!=='kinoko34077')stop('PRINCIPAL_MISMATCH');
 print('PRINCIPAL_OK',{numericIdMatch:true});
 const ins=await call(API+'/user/installations?per_page=100');
 if(ins.status!==200||!Array.isArray(ins.data?.installations))stop('INSTALLATION_LIST_DENIED');
 const matches=ins.data.installations.filter(x=>x.app_slug===EXPECTED_SLUG&&x.account?.login==='kinoko34077');
 if(matches.length!==1)stop('APP_NOT_FOUND_OR_AMBIGUOUS');
 const inst=matches[0];
 const perm=inst.permissions||{};
 const metadataOnly=perm.metadata==='read'&&Object.entries(perm).every(([k,v])=>k==='metadata'||v==='none');
 if(!metadataOnly||inst.repository_selection!=='selected')stop('EFFECTIVE_APP_SCOPE_INVALID');
 const repos=await call(API+'/user/installations/'+inst.id+'/repositories?per_page=100');
 if(repos.status!==200||repos.data?.total_count!==1||repos.data?.repositories?.length!==1||repos.data.repositories[0].id!==REPO_ID)stop('MORE_THAN_ONE_REPO_OR_TARGET_MISMATCH');
 print('APP_SCOPE_OK',{appSlug:EXPECTED_SLUG,metadataReadOnly:true,selectedRepoCount:1,targetRepoIdMatch:true});
 const rm=await call(API+'/repos/'+CANARY);
 if(rm.status!==200||rm.data?.id!==REPO_ID||rm.data?.full_name!==CANARY||rm.data?.private!==true||rm.data?.default_branch!=='main')stop('REPO_METADATA_INVALID');
 const branch=await call(API+'/repos/'+CANARY+'/branches/main');
 const branchDenied=[403,404].includes(branch.status);
 print('NEGATIVE_REST_BRANCH',{status:branch.status,denied:branchDenied,acceptedPermissionHeaderPresent:!!branch.acceptedPermissions});
 if(!branchDenied)stop('REST_BRANCH_NOT_DENIED');
 const h1=await graphql(HEAD_QUERY);
 const h2=await graphql(HEAD_QUERY);
 const extract=(v)=>{if(hasError(v))return null;const d=v.data?.data?.repository;if(d?.databaseId!==REPO_ID||d?.nameWithOwner!==CANARY||d?.isPrivate!==true||d?.defaultBranchRef?.name!=='main')return null;const oid=d.defaultBranchRef?.target?.oid;return /^[0-9a-f]{40}$/.test(oid||'')?oid:null};
 const oid1=extract(h1),oid2=extract(h2);
 print('GRAPHQL_HEAD',{firstStatus:h1.status,secondStatus:h2.status,firstError:!!h1.data?.errors?.length,secondError:!!h2.data?.errors?.length,oidPresent:!!oid1,stable:!!oid1&&oid1===oid2,oid:oid1&&oid1===oid2?oid1:null});
 const blob=await graphql(BLOB_QUERY);
 const byteSize=blob.data?.data?.repository?.object?.byteSize;
 const blobDenied=hasError(blob)||blob.data?.data?.repository?.object===null;
 const blobExposed=typeof byteSize==='number';
 print('NEGATIVE_GRAPHQL_BLOB',{httpStatus:blob.status,apiErrors:!!blob.data?.errors?.length,returnedByteSize:blobExposed,deniedOrNull:blobDenied});
 if(blobExposed){print('VERDICT',{result:'FAIL_B',reason:'CONTENTS_EXPOSED'});return;}
 if(!oid1||!oid2){print('VERDICT',{result:'FAIL_B',reason:'METADATA_ONLY_HEAD_UNAVAILABLE'});return;}
 if(oid1!==oid2){print('VERDICT',{result:'HOLD_B',reason:'HEAD_CHANGED'});return;}
 if(!blobDenied){print('VERDICT',{result:'HOLD_B',reason:'BLOB_DENIAL_INCONCLUSIVE'});return;}
 print('VERDICT',{result:'PASS_B_CANDIDATE',reason:'REQUIRES_INDEPENDENT_HEAD_BRACKET_AND_TEARDOWN',oid:oid1});
}
async function ownerStep(step,expected,url){
 print('OWNER_STEP_REQUIRED',{step,url,reply:expected,tokenNeverPaste:true});
 return await new Promise(resolve=>{
  process.stdin.setEncoding('utf8');process.stdin.resume();
  let timer;
  const onData=v=>{
   if(String(v).trim()!==expected)return;
   clearTimeout(timer);process.stdin.off('data',onData);resolve(true);
  };
  process.stdin.on('data',onData);
  timer=setTimeout(()=>{process.stdin.off('data',onData);resolve(false)},600000);
 });
}
async function teardown(){
 // Separate grant revocation from installation removal: neither implies the other.
 // Optional GitHub App deletion is a further owner-only UI action, NOT inferred here.
 const grantAttested=await ownerStep('REVOKE_USER_AUTHORIZATION','AUTHORIZATION_REVOKED','https://github.com/settings/connections/applications');
 const uninstallAttested=await ownerStep('UNINSTALL_TEMPORARY_APP','APP_UNINSTALLED','https://github.com/settings/installations');
 let status='UNKNOWN';
 try{const r=await call(API+'/user');status=r.status}catch{}
 const revoked=status===401;
 const clean=grantAttested&&uninstallAttested&&revoked;
 print('TEARDOWN_STATUS',{result:clean?'TOKEN_REVOKED_OWNER_APP_UNINSTALL_ATTESTED':'CLEANUP_UNVERIFIED',
   tokenRevoked:revoked,grantRevokeOwnerAttested:grantAttested,ownerAppUninstallConfirmed:uninstallAttested,
   appUninstallIndependentlyVerified:false,refreshTokenRevocationIndependentlyVerified:false});
 if(!clean)process.exitCode=2;
 token=null;process.stdin.pause();
}

async function main(){
 if(typeof CLIENT_ID!=='string'||!/^Iv[0-9A-Za-z]{18,40}$/.test(CLIENT_ID))stop('PUBLIC_CLIENT_ID_INVALID');
 const start=await oauth('/login/device/code',{client_id:CLIENT_ID});
 if(typeof start.device_code!=='string'||!start.device_code||typeof start.user_code!=='string'||!/^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(start.user_code)||start.verification_uri!=='https://github.com/login/device'||start.error)stop('DEVICE_START_INVALID');
 print('AUTHORIZE',{url:'https://github.com/login/device',user_code:start.user_code,expires_in:start.expires_in});
 let interval=Math.max(5,start.interval||5);let expiresAt=Date.now()+Math.min(start.expires_in||900,900)*1000;
 while(Date.now()<expiresAt){
  await pause(interval*1000);
  const r=await oauth('/login/oauth/access_token',{client_id:CLIENT_ID,device_code:start.device_code,grant_type:'urn:ietf:params:oauth:grant-type:device_code',repository_id:String(REPO_ID)});
  if(r.access_token){
   token=r.access_token; r.access_token=null; r.refresh_token=null; // Never log/store even an optional refresh token.
   print('AUTH_DONE',{tokenInMemoryOnly:true,refreshTokenPersisted:false});
   try{await test()}finally{await teardown()}
   return;
  }
  if(r.error==='authorization_pending')continue;
  if(r.error==='slow_down'){interval+=5;continue;}
  stop('OAUTH_POLL_'+(['expired_token','access_denied','authorization_pending','slow_down'].includes(r.error)?r.error.toUpperCase():'UNKNOWN'));
 }
 stop('DEVICE_EXPIRED');
}
main().catch(e=>{if(e.message!=='__HALT__')print('ERROR',{category:e.name||'Exception'});process.exitCode=2});
