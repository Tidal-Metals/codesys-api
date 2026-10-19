// Action WriteOutputs (step 6): the only code that writes physical outputs. It reads requests and permits
// and changes neither.
// ---- implementation ----
GVL_Tags.P_1502_RUN := GVL_Tags.Tags[GVL_Tags.TAG_P_1502_REQUEST].Value > 0.5 AND P_1502_Permit;
