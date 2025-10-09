{{/*
Milvus hostname
*/}}
{{- define "db-meta.milvus-host" -}}
{{- if .Values.milvus.host }}
{{- .Values.milvus.host }}
{{- else }}
{{- .Release.Name -}}-milvus
{{- end }}
{{- end }}
