/* Editable values of the filters (see filter_input.html). Every input carries the
   name of the GET parameter it stands for; pressing Enter reloads the page with
   the edited value, and Escape puts back the one the page was built with. */

$(document).ready(function() {
    $('input.filter-input').each(function() {
        var input = $(this);
        var param = input.data('filterParam');
        var original = input.val();

        input.on('keydown', function(evt) {
            if (evt.key == 'Escape') {
                input.val(original);
                input.trigger('blur');
                return;
            }

            if (evt.key != 'Enter')
                return;

            evt.preventDefault();

            var value = input.val().trim();

            if (value == original.trim())
                return;

            var url = new URL(window.location);

            if (value)
                url.searchParams.set(param, value);
            else
                /* Emptying the field is the same as clicking the cross next to it */
                url.searchParams.delete(param);

            /* The set of results is now a different one, so the page we are on
               within the old set means nothing */
            url.searchParams.delete('page');

            window.location = url.href;
        });

        /* Leaving the field is not a way to apply the value - the page still shows
           the results for the old one, so that is what the field should show too */
        input.on('blur', function() {
            input.val(original);
        });
    });
});
