// Action AppendTag: tag number Index as a "name:value" line, if it changed beyond its deadband, its quality
// changed, or this is a full refresh. The history is not touched here: CommitSent moves it on once the
// message is out. Until quality has its own field on the wire (an open decision, see the design), a tag
// that isn't GOOD is sent as NaN, never as a converted number.
// ---- implementation ----
TagValue := GVL_Tags.PublishSnapshot[Index].Value;
IF IsFullRefresh
		OR GVL_Tags.PublishSnapshot[Index].Quality <> LastSentQuality[Index]
		OR ABS(TagValue - LastSentValue[Index]) > GVL_Tags.TagConfig[Index].Deadband THEN
	// The range test is FALSE for NaN and infinity, and keeps the conversions below inside DINT.
	IF GVL_Tags.PublishSnapshot[Index].Quality <> E_Quality.GOOD OR NOT (TagValue >= -1.0E9 AND TagValue <= 1.0E9) THEN
		ValueText := 'NaN';
	ELSIF GVL_Tags.TagConfig[Index].Kind = E_TagKind.BOOL_TAG THEN
		ValueText := SEL(TagValue > 0.5, '0', '1');
	ELSIF GVL_Tags.TagConfig[Index].Kind = E_TagKind.INT_TAG THEN
		ValueText := DINT_TO_STRING(REAL_TO_DINT(TagValue));
	ELSIF ABS(TagValue) < 1.0E6 THEN    // two decimals: shorter text, and TRUNC stays inside DINT
		ValueText := REAL_TO_STRING(DINT_TO_REAL(TRUNC(TagValue * 100.0 + SEL(TagValue >= 0.0, -0.5, 0.5))) / 100.0);
	ELSE
		ValueText := REAL_TO_STRING(TagValue);
	END_IF
	IsBuildOk := IsBuildOk
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(GVL_Tags.TagConfig[Index].Name), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(':'), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(ValueText), Used := Used)
		AND_THEN AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR('$N'), Used := Used);
	IsInMessage[Index] := TRUE;
END_IF
