FUNCTION AppendGroupReal : BOOL
// Appends ", <value>" to a BCNF-style group line, rounded to two decimals exactly as
// FB_InterlockMatrix.StringPublication does. FALSE (and nothing appended) if it would not fit.
VAR_INPUT
	pBuffer : POINTER TO BYTE;
	Capacity : UDINT;
	Value : REAL;
END_VAR
VAR_IN_OUT
	Used : UDINT;
END_VAR
VAR
	Text : STRING(40);
END_VAR
// ---- implementation ----
Text := CONCAT(', ', REAL_TO_STRING(DINT_TO_REAL(TRUNC(Value * 100.0 + SEL(Value >= 0.0, -0.5, 0.5))) / 100.0));
AppendGroupReal := AppendText(pBuffer := pBuffer, Capacity := Capacity, Text := Text, Used := Used);
