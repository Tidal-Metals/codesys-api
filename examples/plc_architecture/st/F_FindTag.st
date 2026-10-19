FUNCTION F_FindTag : INT
// Index of the tag with this name, 0 if there is none. A linear search is fine for occasional commands;
// with thousands of tags and frequent commands, generate the table sorted by name and search it binarily.
VAR_INPUT
	Name : STRING(24);
END_VAR
VAR
	Index : INT;
END_VAR
// ---- implementation ----
F_FindTag := 0;
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	IF GVL_Tags.TagConfig[Index].Name = Name THEN
		F_FindTag := Index;
		RETURN;
	END_IF
END_FOR
