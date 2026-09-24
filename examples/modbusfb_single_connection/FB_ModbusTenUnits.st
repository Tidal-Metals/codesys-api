{attribute 'no_assign'}
FUNCTION_BLOCK FB_ModbusTenUnits
VAR_INPUT
    xEnable : BOOL := TRUE;
    aGatewayIP : ARRAY[0..3] OF BYTE := [192, 168, 50, 151];
    uiGatewayPort : UINT := 502;
    aUnitIds : ARRAY[1..10] OF UINT := [1,2,3,4,5,6,7,8,9,10];
    uiReadAddress : UINT := 0;
    tRequestGap : TIME := T#0ms;
END_VAR
VAR_OUTPUT
    aRegisters : ARRAY[1..10, 0..1] OF UINT;
    aValid : ARRAY[1..10] OF BOOL;
    aReadCount : ARRAY[1..10] OF UDINT;
    aErrorCount : ARRAY[1..10] OF UDINT;
    aLastError : ARRAY[1..10] OF ModbusFB.Error;
    aLastException : ARRAY[1..10] OF ModbusFB.ExceptionCodes;
    xAllDevicesHealthy : BOOL;
    uiActiveDevice : UINT := 1;
    udiConnectionCount : UDINT;
    udiConnectionErrorCount : UDINT;
    udiCompletedSweeps : UDINT;
END_VAR
VAR
    client : ModbusFB.ClientTCP;
    readHolding : ModbusFB.ClientRequestReadHoldingRegisters;
    requestGap : TON;
    reconnectDelay : TON;
    xReconnectHold : BOOL;
    xWasConnected : BOOL;
    uiState : UINT;
    i : INT;
END_VAR

(* One TCP connection serves every unit ID. Call this FB on every task cycle.
   Configuration changes to gateway IP/port require xEnable FALSE then TRUE. *)
reconnectDelay(IN := xReconnectHold, PT := T#1s);
IF reconnectDelay.Q THEN
    xReconnectHold := FALSE;
END_IF;
client(
    xConnect := xEnable AND NOT xReconnectHold,
    aIPaddr := aGatewayIP,
    uiPort := uiGatewayPort,
    tConnnectTimeOut := T#2s);

IF client.xConnected AND NOT xWasConnected THEN
    udiConnectionCount := udiConnectionCount + 1;
END_IF;
IF NOT client.xConnected THEN
    FOR i := 1 TO 10 DO
        aValid[i] := FALSE;
    END_FOR;
END_IF;
xWasConnected := client.xConnected;

(* A TCP client fault gets a delayed reconnect. A failed RTU request below
   does not close the TCP connection. *)
IF client.xError AND NOT xReconnectHold THEN
    udiConnectionErrorCount := udiConnectionErrorCount + 1;
    xReconnectHold := TRUE;
END_IF;

requestGap(IN := (uiState = 2), PT := tRequestGap);
readHolding(
    rClient := client,
    xExecute := (uiState = 1),
    uiUnitId := aUnitIds[uiActiveDevice],
    uiStartItem := uiReadAddress,
    uiQuantity := 2,
    pData := ADR(aRegisters[uiActiveDevice, 0]),
    udiReplyTimeout := 2000000,
    udiTimeOut := 3000000,
    uiMaxRetries := 0);

CASE uiState OF
    0:  (* Start only after the shared client is connected. *)
        IF xEnable AND client.xConnected THEN
            uiState := 1;
        END_IF;
    1:  (* Keep unit ID and data buffer fixed until completion. *)
        IF readHolding.xDone THEN
            aReadCount[uiActiveDevice] := aReadCount[uiActiveDevice] + 1;
            aValid[uiActiveDevice] := TRUE;
            aLastError[uiActiveDevice] := readHolding.eErrorID;
            aLastException[uiActiveDevice] := readHolding.eException;
            uiState := 2;
        ELSIF readHolding.xError THEN
            aErrorCount[uiActiveDevice] := aErrorCount[uiActiveDevice] + 1;
            aValid[uiActiveDevice] := FALSE;
            aLastError[uiActiveDevice] := readHolding.eErrorID;
            aLastException[uiActiveDevice] := readHolding.eException;
            uiState := 2;
        END_IF;
    2:  (* Reset xExecute and allow a gap before the next request. *)
        IF requestGap.Q AND NOT readHolding.xBusy
           AND NOT readHolding.xDone AND NOT readHolding.xError THEN
            IF uiActiveDevice = 10 THEN
                uiActiveDevice := 1;
                udiCompletedSweeps := udiCompletedSweeps + 1;
            ELSE
                uiActiveDevice := uiActiveDevice + 1;
            END_IF;
            uiState := 0;
        END_IF;
END_CASE;

xAllDevicesHealthy := xEnable AND client.xConnected;
FOR i := 1 TO 10 DO
    xAllDevicesHealthy := xAllDevicesHealthy AND aValid[i];
END_FOR;
END_FUNCTION_BLOCK
