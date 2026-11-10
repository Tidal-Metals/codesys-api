PROGRAM PRG_Comms
VAR
    tcpClient : ModbusFB.ClientTCP;
    serialClient : ModbusFB.ClientSerial;
    readHolding : ModbusFB.ClientRequestReadHoldingRegisters;
    registers : ARRAY[0..9] OF UINT;
    comHandle : SysCom.RTS_IEC_HANDLE;
    comResult : SysCom.RTS_IEC_RESULT;
    mqttClient : MQTT.MQTTClient;
    jsonWriter : JSON.JSONByteArrayWriter;
    serverIp : ARRAY[0..3] OF BYTE := [192, 168, 50, 10];
END_VAR
tcpClient(xConnect := TRUE, aIPAddr := serverIp, uiPort := 502);
readHolding(rClient := tcpClient, uiUnitId := 1, uiStartItem := 0, uiQuantity := 10,
    pData := ADR(registers), xExecute := TRUE);
END_PROGRAM
