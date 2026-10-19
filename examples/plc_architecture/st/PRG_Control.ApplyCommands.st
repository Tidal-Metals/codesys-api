// Action ApplyCommands (step 2): writable tags (setpoints, requests) are written here and nowhere else.
// Takes queued commands, checks them (CheckCommand), applies the accepted ones and answers every one.
// ---- implementation ----
// First scan: writable tags start from their configured defaults. Persisted setpoints, once added
// (a PERSISTENT copy owned by this step), are restored here instead.
IF NOT IsStarted THEN
	IsStarted := TRUE;
	FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
		IF GVL_Tags.TagConfig[Index].IsWritable THEN
			GVL_Tags.Tags[Index].Value := GVL_Tags.TagConfig[Index].DefaultValue;
			GVL_Tags.Tags[Index].Quality := E_Quality.GOOD;
			GVL_Tags.Tags[Index].UpdatedAtMs := NowAtMs;
		END_IF
	END_FOR
END_IF

FOR Index := 1 TO MAX_COMMANDS_PER_SCAN DO
	IF NOT GVL_Tags.Commands.Pop(Item := Command) THEN
		EXIT;
	END_IF
	IsRetry := FALSE;
	IF Command.Result = E_CommandResult.PENDING THEN
		CheckCommand();
		IF NOT IsRetry THEN
			// The ledger holds every checked command with its answer, oldest replaced first. The generator sizes
			// it for all the commands the bridge may send within MAX_COMMAND_AGE_MS; a retry older than that
			// is TOO_OLD anyway. LedgerTooSmall counts entries replaced while still inside that window.
			IF Ledger[NextLedgerSlot].Id <> 0
					AND Ledger[NextLedgerSlot].SentAtMs + MAX_COMMAND_AGE_MS >= WallClockAtMs THEN
				LedgerTooSmall := LedgerTooSmall + 1;
			END_IF
			Ledger[NextLedgerSlot] := Command;
			NextLedgerSlot := (NextLedgerSlot + 1) MOD LEDGER_SIZE;
		END_IF
	END_IF
	IF IsRetry THEN
		RetriesAnswered := RetriesAnswered + 1;
	ELSIF Command.Result = E_CommandResult.ACCEPTED THEN
		GVL_Tags.Tags[Command.TagIndex].Value := Command.Value;
		GVL_Tags.Tags[Command.TagIndex].Quality := E_Quality.GOOD;
		GVL_Tags.Tags[Command.TagIndex].UpdatedAtMs := NowAtMs;
		GVL_Tags.Tags[Command.TagIndex].LastCommandSentAtMs := Command.SentAtMs;
		CommandsAccepted := CommandsAccepted + 1;
	ELSE
		CommandsRejected := CommandsRejected + 1;
	END_IF
	// A full Acks queue never holds a command back: a stop is applied even when its answer can't be queued.
	// The sender then times out and retries the same line, and the ledger answers it.
	IF NOT GVL_Tags.Acks.Push(Item := Command) THEN
		AcksDropped := AcksDropped + 1;
	END_IF
END_FOR

// A trip clears the start request, after the commands so a queued start can't undo it, and moves the trip
// time on for as long as the permit is missing. Uses last scan's permit; the output is already off through it.
IF NOT P_1502_Permit THEN
	GVL_Tags.Tags[GVL_Tags.TAG_P_1502_REQUEST].Value := 0.0;
	P_1502_TrippedAtMs := WallClockAtMs;
END_IF
