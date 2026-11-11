// Action BuildPayload: Payload := _TS:<BuildStampMs>, <BuildSeqKey><BuildSeq>, then padding lines p:000... of at most
// PAD_LINE_CHARS characters until Used is within 3 bytes of BuildTargetBytes (or of the end of Payload). Used is the
// payload's length. Direct byte writes: CONCAT stops at 255 characters.
// ---- implementation ----
Used := 0;
AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := CONCAT('_TS:', ULINT_TO_STRING(BuildStampMs)),
	Used := Used);
AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload),
	Text := CONCAT(CONCAT('$L', BuildSeqKey), UDINT_TO_STRING(BuildSeq)), Used := Used);
PayloadLimit := MIN(BuildTargetBytes, SIZEOF(Payload) - 1);
pPayload := ADR(Payload);
// a padding line is a line feed, 'p:' and at least one '0'; stop when less than that is left
WHILE Used + 4 <= PayloadLimit DO
	LineChars := MIN(PayloadLimit - Used - 1, PAD_LINE_CHARS);
	pPayload[Used] := 16#0A;	// line feed
	pPayload[Used + 1] := 16#70;	// 'p'
	pPayload[Used + 2] := 16#3A;	// ':'
	Used := Used + 3;
	FOR PadIndex := 3 TO LineChars DO
		pPayload[Used] := 16#30;	// '0'
		Used := Used + 1;
	END_FOR
END_WHILE
pPayload[Used] := 0;
