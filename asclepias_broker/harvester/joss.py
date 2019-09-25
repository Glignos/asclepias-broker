#!/usr/bin/env python
from default import BaseRSSFeedParser
import urlparse
import sys
import feedparser
import re
import urllib
from xml.dom import minidom


class JOSSParser(BaseRSSFeedParser):
    """."""

    def __init__(self):
        """."""
        self.control_chars = \
            ''.join(map(unichr, range(0, 32) + range(127, 160)))
        self.control_char_re = \
            re.compile('[%s]' % re.escape(self.control_chars))
        self.errors = []
        self.links = []
        pass

    def remove_control_chars(self, s):
        """."""
        return self.control_char_re.sub('', s)

    def get_records(self, rssURL, data_tag='entry', method='bs', **kwargs):
        """."""
        qparams = urllib.urlencode(kwargs)
        if qparams:
            url = "%s?%s" % (rssURL, qparams)
        else:
            url = rssURL
        source = urllib.urlopen(url)
        mydoc = minidom.parseString(source.read())
        entries = mydoc.getElementsByTagName('entries')
        self.links = mydoc.getElementsByTagName('link')
        doi_url = items[0].firstChild.data
        if 'zenodo' in doi_url:
        req = requests.get(doi_url,  # 'http://dx.doi.org/10.5281/zenodo.228165',
                            allow_redirects=False)

        return entries

    def extract_data(self, entry):
        """."""
        rec = {}
        # By default we put these records in the General database
        # This may be replaced by AST and/or PHY later on
        database = ['GEN']
        # Journal string template
        journal = 'Journal of Open Source Software, vol. %s, issue %s, id. %s'
        # The following keywords are used for comparison with user-supplied
        # keywords for the decision to put a record in the astronomy and/or
        # physics collection
        astro_kw = [
            'astronomy', 'astrophysics', 'planetary sciences', 'solar physics']
        physics_kw = ['physics', 'engineering']
        # Start gathering the necessary fields
        title = entry.find('title').text
        links = {}
        try:
            doi = entry.find('doi').text
        except Exception:
            doi = ''
        try:
            links['DOI'] = doi
        except Exception:
            pass
        try:
            links['PDF'] = entry.find('pdf_url').text
        except Exception:
            pass
        try:
            links['data'] = entry.find('archive_doi').text
        except Exception:
            pass

        rec = {
            'title': title,
            'doi': doi,
            'properties': links
        }

        return rec

    def parse(self, url, **kwargs):
        """."""
        joss_links = {}
        joss_recs = [{}]
        data = self.get_records(url, **kwargs)
        res = []
        for link in self.links:
            link_obj = link.attrs
            if link_obj['href'] and link_obj['rel']:
                res.append(
                    {link_obj['rel'][0]: link_obj['href']})
        for d in data:
            try:
                joss_recs.append(self.extract_data(d))
            except Exception, err:
                sys.stderr.write(
                    'Failed to process record %s (%s). Skipping...\n'
                    % (d.find('id').text, err))
                continue

        parsed_path = urlparse.urlparse(joss_links['last'])
        urlparams = urlparse.parse_qs(parsed_path.query, keep_blank_values=1)
        last_page = int(urlparams['page'][0])
        # if last_page equals 1, we're done
        if last_page == 1:
            return joss_recs

        for i in range(2, last_page+1):
            kwargs['page'] = i
            data += self.get_records(url, **kwargs)
            for d in data:
                try:
                    joss_recs.append(self.extract_data(d))
                except Exception, err:
                    sys.stderr.write(
                        'Failed to process record %s (%s). Skipping...\n'
                        % (d.find('id').text, err))
                    continue

        return joss_recs
