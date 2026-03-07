{{- define "process-management-prototype.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "process-management-prototype.fullname" -}}
{{- printf "%s-%s" (include "process-management-prototype.name" .) .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
