#Requires AutoHotkey v2.0
#SingleInstance Force

; Experimental companion to consumer_programs.py; not a firmware flasher.
; Requires Fn Lock OFF and the six F7-F12 consumer programs installed first.
; No startup registration, device configuration, driver, or admin requirement.
; Bindings are global: other devices' media/browser buttons are also remapped.
; Ordinary F keys and navigation keys are not bound.

Bindings := Map(
    "Volume_Mute", "F1",
    "Volume_Down", "F2",
    "Volume_Up", "F3",
    "Media_Prev", "F4",
    "Media_Play_Pause", "F5",
    "Media_Next", "F6",
    "Browser_Back", "F7",
    "Browser_Forward", "F8",
    "Browser_Refresh", "F9",
    "Browser_Stop", "F10",
    "Browser_Search", "F11",
    "Browser_Favorites", "F12"
)
Owned := Map()

if A_Args.Length = 1 && A_Args[1] = "--check" {
    FileAppend("PASS: consumer bridge parsed; " Bindings.Count " mappings; no hotkeys activated.`n", "*")
    ExitApp()
}
if A_Args.Length != 1 || A_Args[1] != "--run" {
    FileAppend("Usage: AutoHotkey64.exe consumer-bridge.ahk --run`nRequires the matching keyboard configuration; see docs/consumer-bridge.md.`n", "*")
    ExitApp(2)
}

SendMode("Input")
A_IconTip := "HP 460 consumer bridge (experimental)"
OnExit(ReleaseOwned)
for source, target in Bindings {
    Hotkey("*" source, ForwardKey.Bind(target, true))
    Hotkey("*" source " up", ForwardKey.Bind(target, false))
}
Hotkey("^!+Esc", (*) => ExitApp())

ForwardKey(target, down, *) {
    global Owned
    if down {
        Owned[target] := true
        Send("{Blind}{" target " downR}")
    } else if Owned.Has(target) {
        Send("{Blind}{" target " up}")
        Owned.Delete(target)
    }
}

ReleaseOwned(*) {
    global Owned
    for target, _ in Owned
        Send("{Blind}{" target " up}")
}
