Analyze the current git changes and generate a well-formatted commit message, then commit.

## Steps

0. **Ensure git environment is working.** Run `git status` first. If it fails with a "dubious ownership" error (common on WSL paths), run `git config --global --add safe.directory` with the repo path shown in the error message, then retry. All subsequent git commands must be executed from the project root directory (the repo root containing `.git/`).

1. Run `git status` and `git diff` to see all unstaged changes, and `git diff --cached` for staged changes.
2. If nothing is staged, stage all changed files with `git add`. But exclude files that should not be committed (e.g., `.env`, secrets, credentials, large binary files).
3. Analyze the changes and generate a commit message following the Conventional Commits format:

   ```
   <type>: <description>
   ```

   Type must be one of:
   - `feat` — new feature
   - `fix` — bug fix
   - `docs` — documentation only
   - `style` — formatting, no logic change
   - `refactor` — code restructuring, no behavior change
   - `test` — adding or updating tests
   - `chore` — build, dependencies, tooling

4. The description should:
   - Be in Chinese, concise, clearly state what was done
   - Use imperative mood (e.g., "添加" not "添加了")
   - Not exceed 50 characters
   - One commit does one thing — if changes span multiple unrelated tasks, warn the user and suggest splitting

5. Show the user the generated commit message and ask for confirmation before executing `git commit`.
6. After commit, run `git status` to verify.
