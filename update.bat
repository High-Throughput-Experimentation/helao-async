@echo off
call conda activate helao

echo resetting helao-core and pulling updates
cd ..\helao-core
git switch main

git branch -D unstable

git fetch --prune --all

git reset --hard

git pull

git reset --hard

echo[ 

echo resetting helao-async and pulling updates
cd ..\helao-async
git switch main

git branch -D unstable

git fetch --prune --all

git reset --hard

git pull

git reset --hard

echo[ 