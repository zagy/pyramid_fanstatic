# -*- coding: utf-8 -*-
from fanstatic.config import convert_config
from fanstatic.publisher import Publisher
import fanstatic
import os
import wsgiref.util
from pyramid.settings import asbool

CONTENT_TYPES = ['text/html', 'text/xml', 'application/xhtml+xml']

def fanstatic_config(config, prefix='fanstatic.'):
    cfg = {'publisher_signature': fanstatic.DEFAULT_SIGNATURE}
    for k, v in config.items():
        if k.startswith(prefix):
            cfg[k[len(prefix):]] = v
    return convert_config(cfg)


class PublisherTween(object):
    def __init__(self, handler, registry):
        self.config = fanstatic_config(registry.settings)
        self.handler = handler
        self.publisher = Publisher(fanstatic.get_library_registry())
        self.publisher_signature = self.config.get('publisher_signature')
        self.trigger = '/%s/' % self.publisher_signature

    def __call__(self, request):
        if len(request.path_info.split(self.trigger)) > 1:
            path_info = request.path_info
            ignored = request.path_info_pop()
            while ignored != self.publisher_signature:
                ignored = request.path_info_pop()
            response = request.get_response(self.publisher)
            if response.status_int != 404:
                return response
            # forward to handler if the resource could not be found
            request.path_info = path_info

        return self.handler(request)

class InjectorTween(object):
    def __init__(self, handler, registry):
        settings = registry.settings.copy()
        self.use_application_uri = asbool(
            settings.pop('fanstatic.use_application_uri', False))
        self.config = fanstatic_config(settings)
        self.handler = handler
        self.injector = injector_plugin_from_config(self.config)

    def __call__(self, request):
        needed = fanstatic.init_needed(**self.config)
        if self.use_application_uri and not needed.has_base_url():
            base_url = wsgiref.util.application_uri(request.environ)
            # remove trailing slash for fanstatic
            needed.set_base_url(base_url.rstrip('/'))
        request.environ[fanstatic.NEEDED] = needed

        try:
            response = self.handler(request)

            if response.content_type \
                   and response.content_type.lower() in CONTENT_TYPES \
                   and needed.has_resources():

                result = self.injector(response.body, needed, request, response)
                response.body = ''
                response.write(result)

            return response
        finally:
            fanstatic.del_needed()

def injector_plugin_from_config(config):
    if not hasattr(fanstatic.registry, 'InjectorRegistry'):
        # fanstatic < 1.0a3
        def topbottom_injector(html, needed, request=None, response=None):
            return needed.render_topbottom_into_html(html)
        return topbottom_injector

    injector_name = config.get('injector', 'topbottom')
    injector_registry = fanstatic.registry.InjectorRegistry.instance()
    injector_factory = injector_registry.get(injector_name)
    if injector_factory is None:
        raise ConfigurationError(
            'No injector found for name %s' % injector_name)
    return injector_factory(config)


def tween_factory(handler, registry):
    # b/c: compose publisher and injector
    return PublisherTween(InjectorTween(handler, registry), registry)


def includeme(config):
    config.add_tween('pyramid_fanstatic.tween_factory')


def file_callback(dirname, exts=('.less', '.coffee')):
    """Helper to monitor static resources"""
    for var, script in (('LESSC', 'lessc'),):
        if var not in os.environ:
            for dirname in (os.path.join(os.getcwd(), 'bin'),
                            os.path.expanduser('~/bin'),
                            '/usr/local/bin',
                            '/usr/bin'):
                    binary = os.path.join(dirname, script)
                    if os.path.isfile(binary):
                        os.environ[var] = binary
                        break
        if var not in os.environ:
            print(("Can't find a lessc %s binary" % script))

    def callback():
        resources = []
        for root, dirnames, filenames in os.walk(dirname):
            for filename in filenames:
                dummy, ext = os.path.splitext(filename)
                if ext in exts:
                    resources.append(os.path.join(root, filename))
        return resources
    return callback
