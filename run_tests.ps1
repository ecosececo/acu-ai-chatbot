$questions = @(
    @{id="GEN-1"; q="Acibadem Universitesi ne zaman kuruldu?"},
    @{id="GEN-2"; q="Universitenin resmi adi nedir?"},
    @{id="GEN-3"; q="Hangi vakfa bagli?"},
    @{id="GEN-4"; q="Kac fakulte var?"},
    @{id="GEN-5"; q="Kampus nerede?"},
    @{id="FAK-1"; q="Tip Fakultesi kac yillik?"},
    @{id="FAK-2"; q="Eczacilik Fakultesi var mi?"},
    @{id="FAK-3"; q="Saglik Bilimleri Fakultesi hangi bolumleri iceriyor?"},
    @{id="FAK-4"; q="Muhendislik Fakultesi hangi bolumleri iceriyor?"},
    @{id="FAK-5"; q="Insan ve Toplum Bilimleri Fakultesinde ne okunan?"},
    @{id="BOL-1"; q="Bilgisayar Muhendisligi bolumu var mi?"},
    @{id="BOL-2"; q="Biyomedikal Muhendisligi bolumu hangi fakulteye bagli?"},
    @{id="BOL-3"; q="Hemsirelik bolumu kac yillik?"},
    @{id="BOL-4"; q="Fizyoterapi ve Rehabilitasyon bolumu var mi?"},
    @{id="BOL-5"; q="Bilgisayar Muhendisligi ders programi nedir?"},
    @{id="MUF-1"; q="Bilgisayar Muhendisligi bolum baskani kim?"},
    @{id="MUF-2"; q="Muhendislik Fakultesi dekani kim?"},
    @{id="BUR-1"; q="Burs imkanlari neler?"},
    @{id="BUR-2"; q="Burs basvurusu ne zaman yapilir?"},
    @{id="ULU-1"; q="Uluslararasi ogrenciler nasil basvurabilir?"},
    @{id="ULU-2"; q="Erasmus programi var mi?"},
    @{id="KAL-1"; q="Akreditasyon bilgisi nedir?"},
    @{id="SOS-1"; q="Ogrenci kulupler var mi?"},
    @{id="SOS-2"; q="Universitede spor tesisleri var mi?"},
    @{id="LIS-1"; q="Lisansustu programlar neler?"},
    @{id="KAR-1"; q="Kariyer hizmetleri nasil?"},
    @{id="ZOR-1"; q="Hukuk fakultesi var mi?"},
    @{id="ZOR-2"; q="Yazilim Muhendisligi bolumu var mi?"},
    @{id="ZOR-3"; q="Devlet universitesi mi?"},
    @{id="ZOR-4"; q="Muhendislik Fakultesi dekani kim?"},
    @{id="ZOR-5"; q="Universite hangi ilcede?"}
)

$pass = 0
$fail = 0

foreach ($item in $questions) {
    $body = '{"question":"' + $item.q + '"}'
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost/api/chat/" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 120
        $answer = $resp.answer
        $sources = ($resp.sources | ForEach-Object { $_.title }) -join ", "
        Write-Host "[$($item.id)] $($answer.Substring(0, [Math]::Min(100, $answer.Length)))"
        Write-Host "       Sources: $sources"
        $pass++
    } catch {
        Write-Host "[$($item.id)] ERROR: $_" -ForegroundColor Red
        $fail++
    }
    Start-Sleep -Seconds 1
}

Write-Host "`n=== $pass / $($questions.Count) answered, $fail errors ===" -ForegroundColor Cyan
