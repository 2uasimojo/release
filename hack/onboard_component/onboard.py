#!/usr/bin/env python3

import argparse
import os
import re
import sys

import oyaml as yaml

# TODO(efried): Right now this is hardcoded to be specific to my org. Extend it
# to be more generic and customizable. Search for GENERALIZE comments.

# TODO(efried): GENERALIZE: Make these configurable
# The value of an `org/repo` entry under `plugins` in _plugins.yaml
# Right now this is templated off of `openshift`.
PLUGINS_ENTRY = ["approve"]
# The value of branch-protection.orgs.$org.repos.$repo in _config.yaml
# Right now this is templated off of openshift/*-operator
BRANCH_PROTECTION_ENTRY = {
    "required_status_checks": {"contexts": ["ci.ext.devshift.net PR build",],},
}

PROW_CONFIG_DIR = os.path.join("core-services", "prow", "02_config")
CI_OP_CONF_DIR = os.path.join("ci-operator", "config")
CI_OP_JOBS_DIR = os.path.join("ci-operator", "jobs")
TPL_DIR = os.path.join("hack", "onboard_component")
PLUGINS_YAML = os.path.join(PROW_CONFIG_DIR, "_plugins.yaml")
CONFIG_YAML = os.path.join(PROW_CONFIG_DIR, "_config.yaml")

REPO_REGEX = re.compile(r"^([-\w]+)/([-\w]+)$")


def parse_args():
    parser = argparse.ArgumentParser(description="Onboard a new component.")
    parser.add_argument(
        "repo",
        help="The `org/name` of the repository, e.g. `openshift/my-wizbang-operator`",
    )
    return parser.parse_args()


def err(msg):
    print(msg, file=sys.stderr)
    sys.exit(-1)


def load_yaml(fpath):
    """Loads and parses a YAML file and returns the resulting dict."""
    try:
        with open(fpath) as f:
            return yaml.safe_load(f)
    except Exception as e:
        err("Failed to load yaml from %s: %s" % (fpath, e))


def dump_yaml(fpath, content):
    """Writes a structure as YAML to a file. The file is created or
    replaced.
    """
    with open(fpath, "w+") as f:
        f.write(yaml.dump(content, default_flow_style=False))


def load_tpl(fpath, subs):
    """Loads and interpolates a template file containing {format} placeholders,
    returning it as a string.
    """
    try:
        with open(fpath) as f:
            content = f.read()
        return content.format(**subs)
    except Exception as e:
        err(
            "Failed to load and populate template "
            + fpath
            + " with subs "
            + subs
            + "\n"
            + e
        )


def write_from_template(tplname, destpath, **subs):
    """(Over)writes a file from a template.

    :param tplname: Name of the template file, assumed to be in TPL_DIR.
    :param destpath: Relative path to the destination file to be written. E.g.
            'path/to/foo-bar.yaml'.
    :param subs: Substitutions for the template.
    """
    # NOTE: This will replace the file if it already exists. That ought
    # to be okay, if you're using git sanely.
    try:
        ci_int = load_tpl(os.path.join(TPL_DIR, tplname), subs)
        with open(destpath, "w+") as f:
            print("Writing " + destpath)
            f.write(ci_int)
    except Exception as e:
        err("Failed to write " + destpath + ": " + e)


def edit_plugins_yaml(orgrepo):
    plugins_yaml = load_yaml(PLUGINS_YAML)
    plugins = plugins_yaml["plugins"]
    if orgrepo in plugins:
        print(f"'plugins' entry already exists for {orgrepo}.")
        return

    print(f"Adding 'plugins' entry for {orgrepo}.")
    plugins[orgrepo] = PLUGINS_ENTRY

    dump_yaml(PLUGINS_YAML, plugins_yaml)


def ensure_branch_protection(config_yaml, org, repo):
    orgs = config_yaml["branch-protection"]["orgs"]
    if org not in orgs:
        orgs[org] = {}
    if "repos" not in orgs[org]:
        orgs[org]["repos"] = {}
    if repo in orgs[org]["repos"]:
        print(f"Repo {repo} already in 'branch-protection' in _config.yaml")
        return

    print(f"Adding branch-protection entry for {org}/{repo}")
    orgs[org]["repos"][repo] = BRANCH_PROTECTION_ENTRY


def ensure_tide_query(config_yaml, orgrepo):
    # TODO(efried): GENERALIZE
    # Right now this is adding to the .tide.queries list entry containing "our"
    # other components, by looking for a specific one we know of. I don't know
    # what the generalized approach would be -- add a whole new .tide.queries
    # entry?
    tide_queries = config_yaml["tide"]["queries"]
    for query in tide_queries:
        repolist = query.get("repos", [])
        if not repolist:
            continue
        # Check if it's already registered
        if orgrepo in repolist:
            print(f"Tide query already registered for {orgrepo}")
            return
        # TODO(efried): GENERALIZE: That sucking sound is coming from here.
        if "openshift/aws-account-operator" in repolist:
            break
    else:
        err("Couldn't find the right tide/queries section in _config.yaml")

    print(f"Registering tide query for {orgrepo}")
    repolist.append(orgrepo)
    repolist.sort()


def edit_config_yaml(org, repo, orgrepo):
    config_yaml = load_yaml(CONFIG_YAML)
    ensure_branch_protection(config_yaml, org, repo)
    ensure_tide_query(config_yaml, orgrepo)
    dump_yaml(CONFIG_YAML, config_yaml)


def create_ci_operator_config(org, repo, branch):
    destdir = os.path.join(CI_OP_CONF_DIR, org, repo)
    os.makedirs(destdir, exist_ok=True)
    destpath = os.path.join(destdir, f"{org}-{repo}-{branch}.yaml")
    # TODO(efried): GENERALIZE
    # - golang_version: by pulling down the repo and running
    #       $ go mod edit -json | jq -r .Go
    #   (But what's a sane default?)
    # - dockerfile_path: possibly by finding it in the repo?
    # - Whether to include coverage target
    # - Other fields
    golang_version = "golang-1.13"
    write_from_template(
        "ci-operator-config.tpl",
        destpath,
        org=org,
        repo=repo,
        golang_version=golang_version,
    )

def create_postsubmit(org, repo, branch):
    destdir = os.path.join(CI_OP_JOBS_DIR, org, repo)
    os.makedirs(destdir, exist_ok=True)
    destpath = os.path.join(destdir, f"{org}-{repo}-{branch}-postsubmits.yaml")
    write_from_template(
        "postsubmit.tpl",
        destpath,
        org=org,
        repo=repo,
    )

def main():
    args = parse_args()

    # TODO(efried): Do this stuff in an Action instead?
    m = re.search(REPO_REGEX, args.repo)
    if not m:
        err("Malformed repo, expecting something like 'openshift/my-wizbang-operator'")
    orgrepo = m.group(0)
    org = m.group(1)
    repo = m.group(2)

    edit_plugins_yaml(orgrepo)
    edit_config_yaml(org, repo, orgrepo)
    # TODO(efried): GENERALIZE branch here
    create_ci_operator_config(org, repo, "master")
    create_postsubmit(org, repo, "master")

    print(
        f"""
Okay, I did some things. Now you need to:
- Vet the modified/created files.
- Add OWNERS files in the following directories, because I don't know how to do that yet:
  - {CI_OP_CONF_DIR}/{org}/{repo}/
  - ci-operator/jobs/{org}/{repo}/
- Run `make update` to generate jobs files and reformat the YAML as expected by
  the release repo's jobs.
- Check in all the things and push.
"""
    )


if __name__ == "__main__":
    main()
