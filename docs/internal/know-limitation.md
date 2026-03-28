Known limitation (v1):
UI controls are visually disabled during execution, but queued clicks may still be processed after the current synchronous subprocess flow finishes.
A full fix requires moving execution out of the main GUI thread (QThread/QProcess).