{{/*
Create the rabbitmq env var
*/}}
{{- define "fm-app.rabbitmq" -}}
{{- if not .Values.rabbitmqExternalConnection -}}
{{- $releaseName := regexReplaceAll "(-?[^a-z\\d\\-])+-?" (lower .Release.Name) "-" -}}
- name: RABBITMQ_PASSWORD
  valueFrom:
    secretKeyRef:
      name: "{{ $releaseName }}-rabbitmq"
      key: "rabbitmq-password"
- name: WRK_BROKER_CONNECTION
  value: "amqp://user:$(RABBITMQ_PASSWORD)@{{ $releaseName }}-rabbitmq:5672"
{{- end }}
{{- end }}

{{/*
Create the internal db env var
*/}}
{{- define "fm-app.database.internal" -}}
{{- if not .Values.database.internal.password -}}
{{- $releaseName := regexReplaceAll "(-?[^a-z\\d\\-])+-?" (lower .Release.Name) "-" -}}
- name: DATABASE_PASS
  valueFrom:
    secretKeyRef:
      name: "{{ $releaseName }}-postgresql"
      key: "postgres-password"
{{- end }}
{{- end }}

{{/*
Create the internal db env var
*/}}
{{- define "fm-app.database.internal.server" -}}
{{- if .Values.database.internal.server -}}
{{- .Values.database.internal.server -}}
{{- else }}
{{- $releaseName := regexReplaceAll "(-?[^a-z\\d\\-])+-?" (lower .Release.Name) "-" -}}
{{ $releaseName }}-postgresql
{{- end }}
{{- end }}

{{/*
Create db-meta fullname
*/}}
{{- define "fm-app.db-meta.fullname" -}}
{{- $releaseName := regexReplaceAll "(-?[^a-z\\d\\-])+-?" (lower .Release.Name) "-" -}}
{{- printf "%s-%s" $releaseName "db-meta" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
