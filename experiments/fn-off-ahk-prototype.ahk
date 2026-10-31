#Requires AutoHotkey v2.0
#SingleInstance Force

; EXPERIMENTAL AND KNOWN INCOMPLETE.
;
; Fn Lock off makes the navigation cluster native and makes the F-row emit
; its special-action layer. F1-F6 work with these ordinary remaps, and the
; Media_Prev -> F4 test proved that physically held Shift is preserved.
;
; F7-F12 are firmware-generated keyboard chords. The attempted handlers below
; did not reliably suppress those chords: Windows actions such as the emoji
; picker still appeared. F11 (Win+L) is intentionally omitted because a failed
; interception would lock the workstation. Do not install this as a finished
; remapper; it is retained to reproduce the negative result.

Volume_Mute::F1
Volume_Down::F2
Volume_Up::F3
Media_Prev::F4
Media_Play_Pause::F5
Media_Next::F6

*#sc027::{
    Send "{LWin up}{Blind}{F7 down}"
}
*#sc027 Up::{
    Send "{Blind}{F7 up}"
}

F13::F8
ScrollLock::F9

*#i::{
    Send "{LWin up}{Blind}{F10 down}"
}
*#i Up::{
    Send "{Blind}{F10 up}"
}

*^f::{
    Send "{LCtrl up}{Blind}{F12 down}"
}
*^f Up::{
    Send "{Blind}{F12 up}"
}
