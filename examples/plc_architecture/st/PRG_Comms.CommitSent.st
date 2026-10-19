// Action CommitSent: the message went out, so its tags' values become the report-by-exception history.
// The snapshot is unchanged until the next request, so it still holds exactly what was sent.
// ---- implementation ----
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	IF IsInMessage[Index] THEN
		LastSentValue[Index] := GVL_Tags.PublishSnapshot[Index].Value;
		LastSentQuality[Index] := GVL_Tags.PublishSnapshot[Index].Quality;
		IsInMessage[Index] := FALSE;
	END_IF
END_FOR
