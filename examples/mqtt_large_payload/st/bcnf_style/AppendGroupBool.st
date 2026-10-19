FUNCTION AppendGroupBool : BOOL
// Appends ", 0" or ", 1" to a BCNF-style group line, like INT_TO_STRING(BOOL_TO_INT(x)) in BCNF.
VAR_INPUT
	pBuffer : POINTER TO BYTE;
	Capacity : UDINT;
	Value : BOOL;
END_VAR
VAR_IN_OUT
	Used : UDINT;
END_VAR
// ---- implementation ----
AppendGroupBool := AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := SEL(Value, ', 0', ', 1'), Used := Used);
