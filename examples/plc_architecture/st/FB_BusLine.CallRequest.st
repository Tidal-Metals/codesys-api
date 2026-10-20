METHOD CallRequest : BOOL
// Calls the request block of the active read or write. TRUE when it finished (IsDone or IsError). Called with
// IsExecute FALSE once afterwards: the falling edge that lets the same request block start again.
VAR_INPUT
	IsExecute : BOOL;
END_VAR
VAR
	ReplyUs : UDINT;
	TimeoutUs : UDINT;
END_VAR
// ---- implementation ----
ReplyUs := GVL_Bus.Lines[LineIndex].ReplyTimeoutMs * 1000;
TimeoutUs := ReplyUs + 1000000;
IF ActiveWrite <> 0 THEN
	WriteRegister(rClient := Client, xExecute := IsExecute, uiUnitId := GVL_Bus.Writes[ActiveWrite].UnitId,
		uiItem := GVL_Bus.Writes[ActiveWrite].Register, uiValue := INT_TO_UINT(WriteRaw),
		udiReplyTimeout := ReplyUs, udiTimeOut := TimeoutUs, uiMaxRetries := 0);
	IsDone := WriteRegister.xDone;
	IsError := WriteRegister.xError;
	ErrorId := TO_UDINT(WriteRegister.eErrorID);
	Exception := TO_UDINT(WriteRegister.eException);
ELSIF Block.ReadFunction = E_BusFunction.READ_HOLDING_REGISTERS THEN
	ReadHolding(rClient := Client, xExecute := IsExecute, uiUnitId := Block.UnitId, uiStartItem := Block.Start,
		uiQuantity := Block.Count, pData := ADR(Words), udiReplyTimeout := ReplyUs, udiTimeOut := TimeoutUs, uiMaxRetries := 0);
	IsDone := ReadHolding.xDone;
	IsError := ReadHolding.xError;
	ErrorId := TO_UDINT(ReadHolding.eErrorID);
	Exception := TO_UDINT(ReadHolding.eException);
ELSIF Block.ReadFunction = E_BusFunction.READ_INPUT_REGISTERS THEN
	ReadInput(rClient := Client, xExecute := IsExecute, uiUnitId := Block.UnitId, uiStartItem := Block.Start,
		uiQuantity := Block.Count, pData := ADR(Words), udiReplyTimeout := ReplyUs, udiTimeOut := TimeoutUs, uiMaxRetries := 0);
	IsDone := ReadInput.xDone;
	IsError := ReadInput.xError;
	ErrorId := TO_UDINT(ReadInput.eErrorID);
	Exception := TO_UDINT(ReadInput.eException);
ELSIF Block.ReadFunction = E_BusFunction.READ_COILS THEN
	ReadCoils(rClient := Client, xExecute := IsExecute, uiUnitId := Block.UnitId, uiStartItem := Block.Start,
		uiQuantity := Block.Count, pData := ADR(Bits), udiReplyTimeout := ReplyUs, udiTimeOut := TimeoutUs, uiMaxRetries := 0);
	IsDone := ReadCoils.xDone;
	IsError := ReadCoils.xError;
	ErrorId := TO_UDINT(ReadCoils.eErrorID);
	Exception := TO_UDINT(ReadCoils.eException);
ELSE
	ReadDiscrete(rClient := Client, xExecute := IsExecute, uiUnitId := Block.UnitId, uiStartItem := Block.Start,
		uiQuantity := Block.Count, pData := ADR(Bits), udiReplyTimeout := ReplyUs, udiTimeOut := TimeoutUs, uiMaxRetries := 0);
	IsDone := ReadDiscrete.xDone;
	IsError := ReadDiscrete.xError;
	ErrorId := TO_UDINT(ReadDiscrete.eErrorID);
	Exception := TO_UDINT(ReadDiscrete.eException);
END_IF
CallRequest := IsDone OR IsError;
