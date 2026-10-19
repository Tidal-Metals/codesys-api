// Action UpdateValues: new values for every tag, derived from Sequence so the broker check can recompute them.
// ---- implementation ----
FOR Index := 1 TO BOOL_COUNT DO
	Bools[Index] := ((UINT_TO_UDINT(Index) + Sequence) MOD 3) = 0;
END_FOR
FOR Index := 1 TO INT_COUNT DO
	Ints[Index] := UDINT_TO_DINT((UINT_TO_UDINT(Index) * 37 + Sequence) MOD 20000) - 10000;
END_FOR
FOR Index := 1 TO REAL_COUNT DO
	Reals[Index] := DINT_TO_REAL(UDINT_TO_DINT((UINT_TO_UDINT(Index) * 1237 + Sequence * 17) MOD 200000) - 100000) / 100.0;
END_FOR
