# Opens the generated report in Microsoft Word, updates the table of contents and fields, saves the .docx and exports
# the PDF next to it. Usage (from the project root):
#   powershell -ExecutionPolicy Bypass -File reports\final\build\to_pdf.ps1
$docx = (Resolve-Path (Join-Path $PSScriptRoot "..\FinTreX_Analyst_Technical_Report.docx")).Path
$pdf = [System.IO.Path]::ChangeExtension($docx, ".pdf")
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($docx, $false, $false)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Fields.Update() | Out-Null
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Save()
    $doc.ExportAsFixedFormat($pdf, 17)  # 17 = wdExportFormatPDF
    "pages: " + $doc.ComputeStatistics(2) + ", words: " + $doc.ComputeStatistics(0)
    $doc.Close($false)
}
finally {
    $word.Quit()
}
"wrote $pdf"
