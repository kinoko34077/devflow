import unittest
try:
    from tools import development_reconciler as dr
except ImportError:
    dr = None

HEAD='a'*40
OTHER='b'*40

def base(**over):
    data=dict(task_ref='o/r#1', task_kind='FINITE', task_open=True, acceptance_satisfied=True,
              pr_number=7, pr_state='OPEN', pr_head_sha=HEAD, expected_head_sha=HEAD,
              checks='PASS', formal_review='PASS', different_reviewer_required=False,
              different_reviewer='MISSING', request_changes=False, blocking_finding=False,
              owning_blocker=False, human_gate=False, external_wait=False, mergeable=True,
              revertible=True, current_state_changed=False, control_changed=False,
              evidence_complete=True)
    data.update(over); return data

class ReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dr, 'development_reconciler module must exist')
    def test_safe_open_pr_auto_advances(self):
        d=dr.evaluate_pr(base()); self.assertEqual((d.disposition,d.transition),('AUTO_ADVANCE','MERGE_PR'))
    def test_pending_checks_wait_external(self):
        d=dr.evaluate_pr(base(checks='PENDING')); self.assertEqual(d.disposition,'WAIT_EXTERNAL')
    def test_failed_checks_do_not_advance(self):
        d=dr.evaluate_pr(base(checks='FAIL')); self.assertEqual(d.disposition,'NO_ACTION')
    def test_stale_review_needs_evidence(self):
        d=dr.evaluate_pr(base(formal_review='STALE')); self.assertEqual(d.disposition,'NEEDS_EVIDENCE')
    def test_different_reviewer_gate(self):
        d=dr.evaluate_pr(base(different_reviewer_required=True,different_reviewer='MISSING')); self.assertEqual(d.disposition,'NEEDS_REVIEWER')
    def test_human_gate_preempts_merge(self):
        d=dr.evaluate_pr(base(human_gate=True)); self.assertEqual(d.disposition,'NEEDS_HUMAN')
    def test_request_changes_blocks(self):
        d=dr.evaluate_pr(base(request_changes=True)); self.assertEqual(d.disposition,'NO_ACTION')
    def test_merged_finite_task_reconciles(self):
        d=dr.evaluate_pr(base(pr_state='MERGED', current_state_changed=True)); self.assertEqual(d.transition,'POST_MERGE_RECONCILE'); self.assertIn('CLOSE_OWNING_TASK', d.actions); self.assertIn('UPDATE_CURRENT_STATE', d.actions)
    def test_repository_control_never_closes(self):
        d=dr.evaluate_pr(base(task_kind='REPOSITORY_CONTROL', pr_state='MERGED', control_changed=True)); self.assertNotIn('CLOSE_OWNING_TASK', d.actions); self.assertIn('UPDATE_CONTROL', d.actions)
    def test_merge_executor_guards_head_and_is_idempotent(self):
        class T:
            def __init__(self): self.merges=0; self.pr={'state':'open','head_sha':HEAD,'merged':False}
            def get_pr(self, repo, n): return dict(self.pr)
            def merge_pr(self, repo,n,expected): self.assert_expected=expected; self.merges+=1; self.pr={'state':'closed','head_sha':HEAD,'merged':True}; return True
        t=T(); dec=dr.evaluate_pr(base()); r=dr.execute_merge(dec,t,'o/r'); self.assertTrue(r.applied); self.assertEqual(t.merges,1)
        r2=dr.execute_merge(dec,t,'o/r'); self.assertTrue(r2.already_applied); self.assertEqual(t.merges,1)
    def test_merge_executor_refuses_head_move(self):
        class T:
            def get_pr(self,repo,n): return {'state':'open','head_sha':OTHER,'merged':False}
            def merge_pr(self,*a): raise AssertionError('must not merge')
        r=dr.execute_merge(dr.evaluate_pr(base()),T(),'o/r'); self.assertFalse(r.applied); self.assertEqual(r.disposition,'NEEDS_EVIDENCE')

if __name__=='__main__': unittest.main()
