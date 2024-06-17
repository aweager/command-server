#!/bin/zsh

echo Hi on stdout
echo Hi on stderr >&2

echo "Please enter some text, then ^D"
cat
echo "Enter some more"
cat

echo Bye!
