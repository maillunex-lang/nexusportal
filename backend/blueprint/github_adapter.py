"""Read-only façade over the existing portal GitHubClient (no extra credentials)."""
class ReadOnlyGitHub:
    def __init__(self,client):self.client=client
    def get_pr(self,repo,number):return self.client.get_pr(repo,number)
    def check_runs(self,repo,sha):return self.client.check_runs(repo,sha)
    def combined_status(self,repo,sha):return self.client.combined_status(repo,sha)
    def branch_sha(self,repo,branch):return self.client.branch_sha(repo,branch)
    def pr_files(self,repo,number):
        self.client.check_repo(repo)
        files=[]
        for page in range(1,31):
            batch=self.client._req('GET',f'/repos/{repo}/pulls/{number}/files',params={'per_page':100,'page':page})
            files.extend({k:f[k] for k in ('filename','previous_filename','status') if k in f} for f in batch)
            if len(batch)<100:return files
        # GitHub REST caps files at 3000: never pretend a potentially truncated list is complete.
        raise ValueError('Слишком большой PR: проверьте список файлов вручную')
