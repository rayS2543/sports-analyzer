## Git workflow
- Create a new branch for each feature/fix, don't work directly on main
- Ask me before committing — show me the diff first
- Ask before pushing
- Open a PR when the work is ready for review, don't merge automatically

## Before pushing
- Run the test suite (or linter/build, whatever applies) before pushing any commit
- If tests fail, fix the issue before proceeding — don't push broken code
- If there's no test suite yet, at minimum run/build the code to confirm it executes without errors
- Flag to me if you skip this step for any reason
