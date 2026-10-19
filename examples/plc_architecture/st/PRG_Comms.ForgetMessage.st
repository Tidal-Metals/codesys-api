// Action ForgetMessage: the message was too big to build, so nothing was sent. Keep the history as it was
// and make the next message a full refresh, so nothing that changed is lost.
// ---- implementation ----
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	IsInMessage[Index] := FALSE;
END_FOR
IsForceFullRefresh := TRUE;
