{{/*
Create fm-app url
*/}}
{{- define "fm-app.url" -}}
{{- if .Values.api.url }}
{{- .Values.api.url }}
{{- else }}
{{- $releaseName := regexReplaceAll "(-?[^a-z\\d\\-])+-?" (lower .Release.Name) "-" -}}
{{- printf "http://%s-%s:8080" $releaseName "fm-app" | trunc 63 | trimSuffix "-" -}}
{{- end }}
{{- end }}
