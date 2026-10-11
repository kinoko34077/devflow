'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'kinotch_c3b_proof_20261011_hardened.cjs'),'utf8');
const SHA='a'.repeat(40);
function mockResponse(status,payload){
 const raw=Buffer.from(JSON.stringify(payload));
 let read=false;
 return {status,headers:{get(){return null}},async json(){return payload},body:{getReader(){return{
  async read(){if(read)return {done:true};read=true;return {done:false,value:raw}},
  async cancel(){return}
 }}}};
}
async function simulation(options={}){
 let logs=[],userReads=0,headReads=0,confirmations=0,requests=[],exitCode=null,resolveFinished,rejectFinished;
 const completed=new Promise((resolve,reject)=>{resolveFinished=resolve;rejectFinished=reject});
 const timeout=setTimeout(()=>rejectFinished(new Error('local fixture timed out')),3000);
 const stdin={
  setEncoding(){},resume(){},pause(){},on(event,cb){if(event==='data'&&!options.ownerNeverAcknowledges)setImmediate(()=>cb(confirmations++===0?'AUTHORIZATION_REVOKED':'APP_UNINSTALLED'));return this},off(){return this}
 };
 const proc={stdin,exitCode:0,argv:['node','test','Iv'+'X'.repeat(18)]};
 const cons={log(line){logs.push(line);if(line.startsWith('TEARDOWN_STATUS')||(options.terminalHalt&&line.startsWith('HALT'))){clearTimeout(timeout);exitCode=proc.exitCode;resolveFinished({logs,requests,exitCode})}}};
 const allowedUrl=url=>url.startsWith('https://github.com/login/')||url.startsWith('https://api.github.com/');
 async function fakeFetch(url,opt){
  requests.push({url,method:opt?.method||'GET'});
  if(!allowedUrl(url))throw new Error('MOCK_REJECTED_EXTERNAL_URL');
  if(url.endsWith('/login/device/code'))return mockResponse(200,options.oversizeOauth?{junk:'Z'.repeat(70000)}:{device_code:'SYNTHETIC_DEVICE_ONLY',user_code:options.malformedUserCode?'INVALID':'ABCD-EFGH',verification_uri:options.badVerificationUri?'https://evil.example/login':'https://github.com/login/device',expires_in:300,interval:5});
  if(url.endsWith('/login/oauth/access_token'))return mockResponse(200,{access_token:'ghu_SYNTHETIC_DO_NOT_USE'});
  if(url==='https://api.github.com/user'){
   userReads++;return userReads>1?mockResponse(options.tokenRevoked===false?200:401,options.tokenRevoked===false?{id:79015263,login:'kinoko34077'}:{message:'Unauthorized'}):
   mockResponse(200,{id:79015263,login:'kinoko34077'});
  }
  if(url.includes('/user/installations?per_page=100'))return mockResponse(200,{installations:[{
   id:928,app_slug:'kinotch-c3b-meta-proof',account:{login:'kinoko34077'},
   repository_selection:'selected',permissions:options.badPermissions?{metadata:'read',contents:'read'}:{metadata:'read'}
  }]});
  if(url.includes('/user/installations/928/repositories'))return mockResponse(200,{total_count:1,repositories:[{id:1384948130}]});
  if(url.includes('/repos/kinoko34077/kinotch-default-canary/branches/main'))return mockResponse(options.branchReadable?200:403,{message:'Access denied'});
  if(url.includes('/repos/kinoko34077/kinotch-default-canary'))return mockResponse(200,options.oversizeMetadata?{huge:'X'.repeat(270000)}:{id:1384948130,full_name:'kinoko34077/kinotch-default-canary',private:true,default_branch:'main'});
  if(url==='https://api.github.com/graphql'){
   let payload=JSON.parse(opt.body);
   if(payload.query.includes('byteSize'))return mockResponse(200,{data:{repository:{object:options.blobExposed?{byteSize:99}:null}}});
   headReads++;
   return mockResponse(200,options.graphQlDenied?{data:{repository:null},errors:[{type:'FORBIDDEN'}]}:{...(options.graphQlErrorsMalformed?{errors:'MALFORMED'}:{}),data:{repository:{databaseId:1384948130,nameWithOwner:'kinoko34077/kinotch-default-canary',isPrivate:true,defaultBranchRef:{name:'main',target:{oid:options.staleHead&&headReads===2?'b'.repeat(40):SHA}}}}});
  }
  throw new Error('MOCK_UNEXPECTED_API_URL');
 }
 const sandbox={fetch:fakeFetch,process:proc,console:cons,Buffer,URLSearchParams,Date,AbortSignal,
  setTimeout(fn,ms){if(ms>=600000)return options.ownerNeverAcknowledges?setTimeout(fn,0):-1;return setTimeout(fn,0)},clearTimeout(){},
  require:undefined};
 vm.runInNewContext(script,sandbox,{filename:'offline-security-fixture.cjs',timeout:2000});
 return completed;
}
function item(logs,name){const line=logs.find(x=>x.startsWith(name+' '));assert(line,'missing event '+name);return JSON.parse(line.slice(name.length+1))}
test('valid synthetic scope never claims actual PASS_B; cleanup verified',async()=>{
 const a=await simulation();
 assert.equal(item(a.logs,'VERDICT').result,'PASS_B_CANDIDATE');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
 assert.equal(item(a.logs,'TEARDOWN_STATUS').appUninstallIndependentlyVerified,false);
 assert(a.requests.length<=12);
 assert(!a.logs.join('').includes('ghu_SYNTHETIC_DO_NOT_USE'));
});
test('permission mismatch after token still invokes mandatory cleanup',async()=>{
 const a=await simulation({badPermissions:true});
 assert.equal(item(a.logs,'HALT').reason,'EFFECTIVE_APP_SCOPE_INVALID');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('unexpected contents REST read still invokes cleanup',async()=>{
 const a=await simulation({branchReadable:true});
 assert.equal(item(a.logs,'HALT').reason,'REST_BRANCH_NOT_DENIED');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('contents GraphQL byteSize exposure produces FAIL_B but cleans token',async()=>{
 const a=await simulation({blobExposed:true});
 assert.equal(item(a.logs,'VERDICT').result,'FAIL_B');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('revocation not proven cannot be reported as cleanup success',async()=>{
 const a=await simulation({tokenRevoked:false});
 assert.equal(item(a.logs,'TEARDOWN_STATUS').result,'CLEANUP_UNVERIFIED');
});
test('oversized metadata aborts safely and verifies teardown',async()=>{
 const a=await simulation({oversizeMetadata:true});
 assert.equal(item(a.logs,'HALT').reason,'OVERSIZED_API_RESPONSE');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('GraphQL partial denial yields FAIL_B and still revokes',async()=>{
 const a=await simulation({graphQlDenied:true});
 assert.equal(item(a.logs,'VERDICT').result,'FAIL_B');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});

test('malformed GraphQL errors format fails closed even with plausible repository data',async()=>{
 const a=await simulation({graphQlErrorsMalformed:true});
 assert.equal(item(a.logs,'VERDICT').result,'FAIL_B');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('changed GraphQL HEAD within one proof yields HOLD_B',async()=>{
 const a=await simulation({staleHead:true});
 assert.equal(item(a.logs,'VERDICT').result,'HOLD_B');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').tokenRevoked,true);
});
test('owner never confirms revocation and uninstall produces CLEANUP_UNVERIFIED',async()=>{
 const a=await simulation({ownerNeverAcknowledges:true});
 assert.equal(item(a.logs,'TEARDOWN_STATUS').result,'CLEANUP_UNVERIFIED');
 assert.equal(item(a.logs,'TEARDOWN_STATUS').ownerAppUninstallConfirmed,false);
 assert.equal(item(a.logs,'TEARDOWN_STATUS').grantRevokeOwnerAttested,false);
});
test('oversized OAuth response rejected before any token or data API',async()=>{
 const a=await simulation({oversizeOauth:true,terminalHalt:true});
 assert.equal(item(a.logs,'HALT').reason,'OVERSIZED_OAUTH_RESPONSE');
 assert.equal(a.requests.filter(x=>x.url.startsWith('https://api.github.com')).length,0);
});

test('malicious Device Flow verification URL fails before any token use',async()=>{
 const a=await simulation({badVerificationUri:true,terminalHalt:true});
 assert.equal(item(a.logs,'HALT').reason,'DEVICE_START_INVALID');
 assert.equal(a.requests.some(x=>x.url.endsWith('/login/oauth/access_token')),false);
});
test('malformed Device Flow user code fails before any token use',async()=>{
 const a=await simulation({malformedUserCode:true,terminalHalt:true});
 assert.equal(item(a.logs,'HALT').reason,'DEVICE_START_INVALID');
 assert.equal(a.requests.some(x=>x.url.endsWith('/login/oauth/access_token')),false);
});
