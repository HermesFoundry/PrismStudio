# Upstream's workflows, parked

These are Microsoft's CI workflows for their own repository. They are kept
here, unchanged, so that merging upstream stays a merge — but they are out of
`.github/workflows/`, so GitHub does not run them.

They cannot pass on a fork. They want Microsoft's secrets, their self-hosted
runners, their macOS and Windows fleet, their signing and their distro feeds.
On a fork they fail in seconds, on every push, for reasons that have nothing to
do with the code.

If this fork ever wants CI, it should be a workflow written for what this
repository actually is, not these. Move a file back into `.github/workflows/`
if you want to try one.
