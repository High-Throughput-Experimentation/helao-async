@echo off
call conda activate helao

cd ..\helao-core

git fetch --all
git switch main

git branch -D unstable
git switch unstable

git switch %1

echo[ 

cd ..\helao-async

git fetch --all
git switch main

git branch -D unstable
git switch unstable

git switch %1

echo[ 