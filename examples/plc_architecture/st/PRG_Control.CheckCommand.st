// Action CheckCommand (part of step 2): sets Command.Result for a PENDING command. ACCEPTED means it may be
// applied. Range checks are written as NOT (inside) so that NaN and infinity count as outside.
// ---- implementation ----
// A retry is the identical line sent again: same id, tag, value and timestamp. It gets the first answer and
// is never applied twice. The same id with other content is a different command and is checked as new.
FOR Slot := 0 TO LEDGER_SIZE - 1 DO
	IF Ledger[Slot].Id = Command.Id AND Ledger[Slot].SentAtMs = Command.SentAtMs
			AND Ledger[Slot].TagIndex = Command.TagIndex AND Ledger[Slot].Value = Command.Value THEN
		Command.Result := Ledger[Slot].Result;
		IsRetry := TRUE;
		RETURN;
	END_IF
END_FOR

IF Command.TagIndex = 0 THEN
	Command.Result := E_CommandResult.UNKNOWN_TAG;
ELSIF NOT GVL_Tags.TagConfig[Command.TagIndex].IsWritable THEN
	Command.Result := E_CommandResult.NOT_WRITABLE;
ELSIF NOT (Command.Value >= GVL_Tags.TagConfig[Command.TagIndex].MinValue
		AND Command.Value <= GVL_Tags.TagConfig[Command.TagIndex].MaxValue) THEN
	Command.Result := E_CommandResult.OUT_OF_RANGE;
ELSIF GVL_Tags.TagConfig[Command.TagIndex].Kind = E_TagKind.BOOL_TAG
		AND Command.Value <> 0.0 AND Command.Value <> 1.0 THEN
	Command.Result := E_CommandResult.OUT_OF_RANGE;
// Converted only once the value is inside the tag's range, which the generator keeps inside DINT.
ELSIF GVL_Tags.TagConfig[Command.TagIndex].Kind = E_TagKind.INT_TAG
		AND_THEN Command.Value <> DINT_TO_REAL(REAL_TO_DINT(Command.Value)) THEN
	Command.Result := E_CommandResult.OUT_OF_RANGE;
ELSIF WallClockAtMs < MIN_PLAUSIBLE_WALL_CLOCK_MS THEN
	Command.Result := E_CommandResult.CLOCK_NOT_SYNCED;
ELSIF Command.SentAtMs > WallClockAtMs + MAX_FUTURE_SKEW_MS
		OR Command.SentAtMs + MAX_COMMAND_AGE_MS < WallClockAtMs
		OR (Command.ReceivedAtMs < NowAtMs AND NowAtMs - Command.ReceivedAtMs > MAX_QUEUE_AGE_MS) THEN
	Command.Result := E_CommandResult.TOO_OLD;
// Every timestamp comes from one clock, the bridge's (the only command sender), so they can be ordered.
ELSIF Command.SentAtMs < GVL_Tags.Tags[Command.TagIndex].LastCommandSentAtMs THEN
	Command.Result := E_CommandResult.OUT_OF_ORDER;      // a newer command for this tag already applied
// A start must be sent after the permit came back, with the clock skew as margin. A start that was queued
// or delayed across a trip, or retried after one, is refused.
ELSIF Command.TagIndex = GVL_Tags.TAG_P_1502_REQUEST AND Command.Value > 0.5
		AND (NOT P_1502_Permit OR Command.SentAtMs <= P_1502_TrippedAtMs + MAX_FUTURE_SKEW_MS) THEN
	Command.Result := E_CommandResult.INTERLOCKED;
ELSE
	Command.Result := E_CommandResult.ACCEPTED;
END_IF
