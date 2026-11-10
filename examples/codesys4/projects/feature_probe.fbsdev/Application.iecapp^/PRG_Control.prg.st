PROGRAM PRG_Control
VAR RETAIN
    retainedCount : UDINT;
END_VAR
VAR PERSISTENT
    lastCommandId : UDINT;
END_VAR
VAR
    nowMs : UDINT;
    timestamp : ULINT;
    rtcResult : UDINT;
    dynamicBuffer : POINTER TO BYTE;
END_VAR
retainedCount := retainedCount + 1;
nowMs := SysTimeCore.SysTimeGetMs();
rtcResult := SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := timestamp);
lastCommandId := lastCommandId + 1;
END_PROGRAM
