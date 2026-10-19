PROGRAM BcnfPayloadExample
// Sketch of BCNF's StringPublication without the 255-character cap: every group goes into one
// buffer, one "[GROUP, v1, v2, ...]" line per group, so a single publisher sends all of them.
// The values are copied into arrays first; that snapshot is also what a separate MQTT task needs.
// Compiled against the demo project; not run on a PLC.
VAR_INPUT
	IsBuildRequested : BOOL;            // set by the publish timer, not every scan
END_VAR
VAR_OUTPUT
	IsBuildOk : BOOL;                   // FALSE: buffer too small, do not publish this message
	PayloadLength : UDINT;
END_VAR
VAR
	Analog : ARRAY[1..14] OF REAL;      // AIT_1508_V, FIT_1506_F, ... in publish-map order
	Digital : ARRAY[1..9] OF BOOL;      // BCNF_H_E_STOP, LSL_1503_S, ...
	Payload : STRING(4000);
	Used : UDINT;
	Index : INT;
END_VAR
// ---- implementation ----
IF NOT IsBuildRequested THEN
	RETURN;   // BCNF rebuilds its strings every scan today; once per publish is enough
END_IF

// Snapshot (in BCNF: Analog[1] := AIT_1508_V; Analog[2] := FIT_1506_F; ...)

Used := 0;
Payload := '';
IsBuildOk := AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := '[BCNF_ANALOG', Used := Used);
FOR Index := 1 TO 14 DO
	IsBuildOk := IsBuildOk AND_THEN AppendGroupReal(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Value := Analog[Index], Used := Used);
END_FOR
IsBuildOk := IsBuildOk AND_THEN AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := ']$N[BCNF_DIGITAL', Used := Used);
FOR Index := 1 TO 9 DO
	IsBuildOk := IsBuildOk AND_THEN AppendGroupBool(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Value := Digital[Index], Used := Used);
END_FOR
IsBuildOk := IsBuildOk AND_THEN AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := ']$N', Used := Used);
// ... the same for BCNF_ALARM, BCNF_SETPOINT_1 and _2 (one line once the bridge's publish map
// has a single setpoint entry), BCNF_OUTPUT_OTHER and BCNF_STATUS_STRING.
PayloadLength := Used;
// Publish with PayloadString := ADR(Payload) only when IsBuildOk is TRUE.
