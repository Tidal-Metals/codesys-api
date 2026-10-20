// Action BuildTag: appends tag number Index in the selected format.
// Values are formatted as BCNF formats each type; only the text around them differs between formats.
// ---- implementation ----
// Measurement aid: OnlyKind limits the build to one type (4 = none) to time each type separately.
IF Index <= BOOL_COUNT THEN
	Kind := 1;
ELSIF Index <= BOOL_COUNT + INT_COUNT THEN
	Kind := 2;
ELSE
	Kind := 3;
END_IF
IF OnlyKind <> 0 AND OnlyKind <> Kind THEN
	RETURN;
END_IF

IF Index <= BOOL_COUNT THEN
	ValueText := SEL(Bools[Index], '0', '1');
ELSIF Index <= BOOL_COUNT + INT_COUNT THEN
	ValueText := DINT_TO_STRING(Ints[Index - BOOL_COUNT]);
ELSE
	RealValue := Reals[Index - BOOL_COUNT - INT_COUNT];
	ValueText := REAL_TO_STRING(DINT_TO_REAL(TRUNC(RealValue * 100.0 + SEL(RealValue >= 0.0, -0.5, 0.5))) / 100.0);
END_IF

IF IsTagValueFormat THEN
	// TT-1001:1, or TT-1001:1:1792445443883 with a timestamp
	IF TimestampMode = 2 THEN
		StampText := CONCAT(':', ULINT_TO_STRING(StampMs));   // same time, converted again: what a per-tag time costs
	END_IF
	IsBuildOk := IsBuildOk
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(Names[Index]), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(':'), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(ValueText), Used := Used)
		AND_THEN (TimestampMode = 0
			OR_ELSE AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(StampText), Used := Used))
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR('$N'), Used := Used);
ELSE
	// [G1, v1, v2, ... v100]
	IF (Index - 1) MOD GROUP_SIZE = 0 THEN
		Header := CONCAT('[G', UINT_TO_STRING((Index - 1) / GROUP_SIZE + 1));
		IsBuildOk := IsBuildOk AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(Header), Used := Used);
	END_IF
	IsBuildOk := IsBuildOk
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(', '), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(ValueText), Used := Used);
	IF Index MOD GROUP_SIZE = 0 THEN
		IsBuildOk := IsBuildOk AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(']$N'), Used := Used);
	END_IF
END_IF
