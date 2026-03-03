# This ***REMOVED***le must be used with "source <venv>/bin/activate.***REMOVED***sh" *from ***REMOVED***sh*
# (https://***REMOVED***shshell.com/); you cannot run it directly.

function deactivate  -d "Exit virtual environment and return to normal shell environment"
    # reset old environment variables
    if test -n "$_OLD_VIRTUAL_PATH"
        set -gx PATH $_OLD_VIRTUAL_PATH
        set -e _OLD_VIRTUAL_PATH
    end
    if test -n "$_OLD_VIRTUAL_PYTHONHOME"
        set -gx PYTHONHOME $_OLD_VIRTUAL_PYTHONHOME
        set -e _OLD_VIRTUAL_PYTHONHOME
    end

    if test -n "$_OLD_FISH_PROMPT_OVERRIDE"
        functions -e ***REMOVED***sh_prompt
        set -e _OLD_FISH_PROMPT_OVERRIDE
        functions -c _old_***REMOVED***sh_prompt ***REMOVED***sh_prompt
        functions -e _old_***REMOVED***sh_prompt
    end

    set -e VIRTUAL_ENV
    if test "$argv[1]" != "nondestructive"
        # Self-destruct!
        functions -e deactivate
    end
end

# Unset irrelevant variables.
deactivate nondestructive

set -gx VIRTUAL_ENV "/Users/naheeminnis/Development/process-management-prototype/venv"

set -gx _OLD_VIRTUAL_PATH $PATH
set -gx PATH "$VIRTUAL_ENV/bin" $PATH

# Unset PYTHONHOME if set.
if set -q PYTHONHOME
    set -gx _OLD_VIRTUAL_PYTHONHOME $PYTHONHOME
    set -e PYTHONHOME
end

if test -z "$VIRTUAL_ENV_DISABLE_PROMPT"
    # ***REMOVED***sh uses a function instead of an env var to generate the prompt.

    # Save the current ***REMOVED***sh_prompt function as the function _old_***REMOVED***sh_prompt.
    functions -c ***REMOVED***sh_prompt _old_***REMOVED***sh_prompt

    # With the original prompt function renamed, we can override with our own.
    function ***REMOVED***sh_prompt
        # Save the return status of the last command.
        set -l old_status $status

        # Output the venv prompt; color taken from the blue of the Python logo.
        printf "%s%s%s" (set_color 4B8BBE) "(venv) " (set_color normal)

        # Restore the return status of the previous command.
        echo "exit $old_status" | .
        # Output the original/"old" prompt.
        _old_***REMOVED***sh_prompt
    end

    set -gx _OLD_FISH_PROMPT_OVERRIDE "$VIRTUAL_ENV"
end
