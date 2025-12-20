from django.db import connections, transaction
from django.shortcuts import redirect

from urllib.parse import urlencode


#@transaction.commit_on_success
def db_query(string, params, db='fram', debug=False, simplify=True):
    connection = connections[db]

    cursor = connection.cursor()
    result = None

    if debug:
        print(cursor.mogrify(string, params))

    try:
        cursor.execute(string, params)
        try:
            columns = [col[0] for col in cursor.description]
            result = [dict(zip(columns, row)) for row in cursor.fetchall()]

            if simplify and len(result) == 1:
                if len(result[0]) == 1:
                    result = result[0][0]
                else:
                    result = result[0]
        except:
            # No data returned
            result = None
    except:
        import traceback
        traceback.print_exc()
        pass
    finally:
        cursor.close()

    return result


def redirect_get(url_or_view, *args, **kwargs):
    get_params = kwargs.pop('get', None)

    response = redirect(url_or_view, *args, **kwargs)
    if get_params:
        response['Location'] += '?' + urlencode(get_params)

    return response


from django.core.exceptions import PermissionDenied

class IgnorePermissionDeniedFilter:
    def filter(self, record):
        # Django stores the exception info in record.exc_info
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if isinstance(exc_value, PermissionDenied):
                return False
        return True
