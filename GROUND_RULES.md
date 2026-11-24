# Ground rules: what may go into this repository

AllegianceVR is a public fork. Everything committed here, and every issue, PR and comment, is world-readable and
stays in history even after a later commit removes it.

1. **No org-restricted data (as defined by your org policy) or client data.** This project has none to begin with.
   Keep it that way.
2. **No secrets.** No passwords, API keys, tokens, private keys or signing material in files, commit messages, issues
   or PRs. A secret that reaches GitHub is burned: report it to the operator so it can be revoked.
3. **No personal or host details.** No email addresses (other than an agent's noreply commit address), real names
   beyond public GitHub handles, host names, device serials or machine paths. Describe a machine by its role ("the VR
   test PC").
4. **No game assets or code from other projects** beyond what the upstream GPL licence and the fork already carry.
   Link to a third-party source rather than copying it.

`python tools/check_data_boundary.py` is a narrow tripwire for the obvious secret shapes. It does not replace reading
what you are about to commit.
