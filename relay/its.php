<?php
// ITS 국가교통정보센터 중계 (국내 서버용). 해외(GitHub) 에서는 ITS 가 막히므로 이 파일을 거쳐 호출.
// 사용: its.php?token=비밀값&ep=trafficInfo&type=all&getType=json&minX=..&maxX=..&minY=..&maxY=..
//       its.php?token=비밀값&ep=eventInfo&type=all&eventType=all&getType=json&minX=..
// 아래 두 값만 채우세요.
$ITS_KEY = "여기에_ITS_인증키";
$TOKEN   = "여기에_아무_비밀문자열";   // GitHub 비밀값 ITS_RELAY_TOKEN 과 똑같이

header("Content-Type: application/json; charset=utf-8");
header("Cache-Control: no-store");
if (!isset($_GET["token"]) || !hash_equals($TOKEN, (string)$_GET["token"])) {
    http_response_code(403); echo '{"error":"forbidden"}'; exit;
}
$ep = isset($_GET["ep"]) && $_GET["ep"] === "eventInfo" ? "eventInfo" : "trafficInfo";
$allowed = ["type","getType","eventType","minX","maxX","minY","maxY"];
$q = ["apiKey" => $ITS_KEY];
foreach ($allowed as $k) if (isset($_GET[$k])) $q[$k] = $_GET[$k];
$url = "https://openapi.its.go.kr:9443/" . $ep . "?" . http_build_query($q);

// 60초 캐시 (같은 요청 반복 시 ITS 호출 절약)
$cache = sys_get_temp_dir() . "/its_" . md5($url) . ".json";
if (file_exists($cache) && time() - filemtime($cache) < 60) { readfile($cache); exit; }

$ch = curl_init($url);
curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 25, CURLOPT_CONNECTTIMEOUT => 10,
                        CURLOPT_SSL_VERIFYPEER => true, CURLOPT_FOLLOWLOCATION => true]);
$body = curl_exec($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err  = curl_error($ch);
curl_close($ch);
if ($body === false || $code != 200) {
    http_response_code(502);
    echo json_encode(["error" => "its_failed", "http" => $code, "detail" => $err]);
    exit;
}
@file_put_contents($cache, $body);
echo $body;
