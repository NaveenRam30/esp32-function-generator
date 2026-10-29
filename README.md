# ESP32 Function Generator with Python GUI

This repository keeps firmware and desktop software on separate long-lived branches.

| Branch | Contents | Release tags |
| --- | --- | --- |
| `main` | Project overview and team information | None |
| `esp32-firmware` | ESP32 Arduino sketch and firmware documentation | `firmware-v1.0.0` |
| `python-gui` | Python desktop application and GUI documentation | `gui-v1.0.0`, `gui-v2.0.0` |

Select the relevant branch in GitHub's branch menu. The two application branches
intentionally contain different files. Component work merges into its component
branch; neither component branch is merged into main in this repository layout.

To keep both components available locally, clone once and add worktrees:

```bash
git clone https://github.com/OWNER/esp32-function-generator.git
cd esp32-function-generator
git worktree add ../function-generator-firmware esp32-firmware
git worktree add ../function-generator-gui python-gui
```

Flash the sketch from the firmware worktree, then run `python main.py` in the
GUI worktree after installing requirements. GUI V1 and V2 use identical firmware
and serial protocol. The preview is calculated rather than measured output.

This completed project is being imported into version control now. Import dates
are not original development dates. See CONTRIBUTORS.md for verified team roles.

Issue/PR label definitions are in `.github/labels.json`; create these labels on
GitHub manually. Tags are repository-wide, so prefix component versions with
`firmware-` and `gui-`. GUI V2 is a milestone name for a compatible visual update.
