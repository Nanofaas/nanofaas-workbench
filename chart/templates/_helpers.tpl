{{- define "wb.name" -}}
wb-{{ required "instance is required" .Values.instance }}
{{- end -}}

{{/* call with (dict "root" $ "component" "prometheus") */}}
{{- define "wb.labels" -}}
nanofaas.workbench/instance: {{ .root.Values.instance | quote }}
nanofaas.workbench/component: {{ .component | quote }}
{{- end -}}

{{- define "wb.resources" -}}
{{- if . }}
resources:
  requests: {{- toYaml . | nindent 4 }}
  limits: {{- toYaml . | nindent 4 }}
{{- end }}
{{- end -}}

{{/* A ConfigMap carrying the role-rendered files, byte for byte. */}}
{{- define "wb.configmap" -}}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "wb.name" .root }}
  labels: {{- include "wb.labels" . | nindent 4 }}
data: {{- toYaml .files | nindent 2 }}
{{- end -}}

{{/* A ClusterIP Service for the one port of a pod-selected component. */}}
{{- define "wb.service" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "wb.name" .root }}
  labels: {{- include "wb.labels" . | nindent 4 }}
spec:
  selector:
    nanofaas.workbench/instance: {{ .root.Values.instance | quote }}
  ports:
    - port: {{ .port }}
      targetPort: {{ .target }}
{{- end -}}

{{/* Files mounted one by one at a directory, via subPath. */}}
{{- define "wb.filemounts" -}}
{{- range $name, $_ := .files }}
- name: config
  mountPath: {{ $.dir }}/{{ $name }}
  subPath: {{ $name }}
  readOnly: true
{{- end }}
{{- end -}}

{{- define "wb.hardened" -}}
securityContext:
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
{{- end -}}
