METHOD PublishReceived : BOOL
VAR_INPUT
	Data : MQTT.CALLBACK_DATA;
END_VAR
VAR
	Command : ST_Command;
	Rest : STRING(255);
	IdText : STRING(40);
	ValueText : STRING(40);
	TimeText : STRING(40);
	FirstComma : INT;
	EqualsAt : INT;
	SecondComma : INT;
END_VAR
// ---- implementation ----
// Copy the payload now: the library reuses its buffer for the next message. The copy stops at SIZEOF(Line);
// the length test below rejects a message that was cut short or holds a NUL.
Line := Data.PayloadString^;
ReceivedCount := ReceivedCount + 1;
Command.ReceivedAtMs := F_NowMs();
Command.Result := E_CommandResult.MALFORMED;

// Keep the id whenever it is readable, so even a malformed command gets an answer the sender can match.
FirstComma := FIND(Line, ',');
IF FirstComma > 1 THEN
	IdText := LEFT(Line, FirstComma - 1);
	IF F_IsNumberText(Text := IdText, IsDigitsOnly := TRUE, MaxLength := 9) THEN
		Command.Id := STRING_TO_UDINT(IdText);
	END_IF
END_IF

EqualsAt := FIND(Line, '=');
Rest := RIGHT(Line, LEN(Line) - EqualsAt);
SecondComma := FIND(Rest, ',');
ValueText := LEFT(Rest, SecondComma - 1);
TimeText := RIGHT(Rest, LEN(Rest) - SecondComma);
IF Data.PayloadSize = INT_TO_UDINT(LEN(Line)) AND Command.Id <> 0 AND EqualsAt > FirstComma + 1 AND SecondComma > 1
		AND F_IsNumberText(Text := ValueText, IsDigitsOnly := FALSE, MaxLength := 15)
		AND F_IsNumberText(Text := TimeText, IsDigitsOnly := TRUE, MaxLength := 15) THEN
	Command.TagIndex := F_FindTag(Name := MID(Line, EqualsAt - FirstComma - 1, FirstComma + 1));
	Command.Value := STRING_TO_REAL(ValueText);
	Command.SentAtMs := STRING_TO_ULINT(TimeText);
	Command.Result := E_CommandResult.PENDING;
ELSE
	MalformedCount := MalformedCount + 1;   // still queued: the control task (the only Acks producer) answers it
END_IF

IF NOT GVL_Tags.Commands.Push(Item := Command) THEN
	DroppedCount := DroppedCount + 1;       // no answer: the sender times out and retries with the same id
END_IF
PublishReceived := TRUE;
