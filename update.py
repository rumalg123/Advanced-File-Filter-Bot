import os
from logging import (
    error as log_error,
    info as log_info,
)
from os import path
from subprocess import run as srun

UPSTREAM_REPO = os.environ.get('UPSTREAM_REPO', "https://github.com/rumalg123/Advanced-File-Filter-Bot")

UPSTREAM_BRANCH = os.environ.get('UPSTREAM_BRANCH', "main")

if UPSTREAM_REPO:
    if path.exists(".git"):
        srun(["rm", "-rf", ".git"])

    update = srun(
        [
            f"git init -q \
                     && git config --global user.email rumalg123@gmail.com \
                     && git config --global user.name Rumal \
                     && git add . \
                     && git commit -sm update -q \
                     && git remote add origin {UPSTREAM_REPO} \
                     && git fetch origin -q \
                     && git reset --hard origin/{UPSTREAM_BRANCH} -q"
        ],
        shell=True,
    )

    if update.returncode == 0:
        log_info("Successfully updated with latest commit from UPSTREAM_REPO")
    else:
        log_error(
            "Something went wrong while updating, check UPSTREAM_REPO if valid or not!"
        )