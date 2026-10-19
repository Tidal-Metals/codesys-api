FUNCTION AppendTagLine : BOOL
// Appends "<Name>:<Value>\n", the line format the bridge ingests directly, without a publish map.
// All or nothing: if the whole line doesn't fit, the buffer is left as it was and FALSE is returned.
VAR_INPUT
	pBuffer : POINTER TO BYTE;
	Capacity : UDINT;
	Name : STRING(64);                  // the bridge's tag key for this value
	Value : STRING(40);                 // already formatted, e.g. by REAL_TO_STRING
END_VAR
VAR_IN_OUT
	Used : UDINT;
END_VAR
VAR
	Start : UDINT;
END_VAR
// ---- implementation ----
Start := Used;
AppendTagLine := AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := Name, Used := Used)
	AND_THEN AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := ':', Used := Used)
	AND_THEN AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := Value, Used := Used)
	AND_THEN AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := '$N', Used := Used);
IF NOT AppendTagLine AND pBuffer <> 0 THEN
	Used := Start;
	pBuffer[Start] := 0;
END_IF
