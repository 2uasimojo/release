base_images:
  base:
    cluster: https://api.ci.openshift.org
    name: "4.4"
    namespace: ocp
    tag: base
build_root:
  image_stream_tag:
    cluster: https://api.ci.openshift.org
    name: release
    namespace: openshift
    tag: {golang_version}
images:
- dockerfile_path: build/Dockerfile
  from: base
  to: {repo}
resources:
  '*':
    requests:
      cpu: 100m
      memory: 200Mi
tests:
- as: coverage
  commands: |
    export CODECOV_TOKEN=$(cat /tmp/secret/CODECOV_TOKEN)
    make coverage
  container:
    from: src
  secret:
    mount_path: /tmp/secret
    name: {repo}-codecov-token
zz_generated_metadata:
  branch: master
  org: {org}
  repo: {repo}
