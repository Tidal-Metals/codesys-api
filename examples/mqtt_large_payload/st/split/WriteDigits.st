FUNCTION WriteDigits : BOOL
// Writes Value as exactly Digits ASCII decimal digits (leading zeros, higher digits dropped) at pDest.
VAR_INPUT
	pDest : POINTER TO BYTE;
	Value : UDINT;
	Digits : UDINT;
END_VAR
VAR
	Position : UDINT;
	Rest : UDINT;
END_VAR
// ---- implementation ----
Rest := Value;
FOR Position := Digits TO 1 BY -1 DO
	pDest[Position - 1] := UDINT_TO_BYTE(48 + Rest MOD 10);
	Rest := Rest / 10;
END_FOR
WriteDigits := TRUE;
