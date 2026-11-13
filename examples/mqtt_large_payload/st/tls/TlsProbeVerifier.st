// Peer-certificate callback for TlsProbe (CmpTlsCreateContext2): CmpTls calls VerifyCertCallback inside
// SysSock2Connect, after its own chain check. The certificate is accepted only if that check passed and, with
// IsHostCheckEnabled, the runtime checker (X509CertCheckHost for ExpectedDns, else X509CertCheckIP for ExpectedIp)
// says the certificate names the broker. Exactly one identity is checked. Records what it saw (SANs: diagnostics).
FUNCTION_BLOCK TlsProbeVerifier IMPLEMENTS CmpTls.IVerifyCertCallback
VAR_INPUT
	IsHostCheckEnabled : BOOL := TRUE;
	ExpectedIp : UDINT;          // as in SOCKADDRESS.sin_addr.ulAddr; 0 matches no IP entry
	ExpectedDns : STRING(80);    // a name to check; when set, ExpectedIp is not used
	IsSanDumped : BOOL := TRUE;  // read the SubjectAltNames into AltTypes/AltIps/AltDns (diagnostics only)
END_VAR
VAR_OUTPUT
	Calls : UDINT;
	LastVerifyResult : UDINT;    // CmpTls's own verdict on the chain
	LastContentResult : UDINT;   // X509CertInfoInit / X509CertGetContent
	LastExitResult : UDINT;      // X509CertInfoExit
	LastHostCheckResult : UDINT; // pResult of X509CertCheckHost / X509CertCheckIP
	CheckedBy : STRING(8);       // name, ip or none
	LastAltNameCount : UDINT;
	AltTypes : ARRAY[0..3] OF INT;
	AltIps : ARRAY[0..3] OF UDINT;
	AltDns : ARRAY[0..1] OF STRING(80);
	IsHostMatched : BOOL;
	LastReturn : UDINT;          // 0 accepts
END_VAR
VAR
	Info : CmpX509Cert.RtsX509CertInfo;
	Alt : POINTER TO CmpX509Cert.RtsX509AltName;
	I : UDINT;
	DnsCount : INT;
	CheckIp : SysSocket2.INADDR;
END_VAR
// ---- implementation ----
