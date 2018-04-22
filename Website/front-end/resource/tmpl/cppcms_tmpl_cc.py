#!/usr/bin/env python

############################################################################
#
#  Copyright (C) 2008-2012  Artyom Beilis (Tonkikh) <artyomtnk@yahoo.com>     
#                                                                             
#  See accompanying file COPYING.TXT file for licensing details.
#
############################################################################

import os
import re
import sys
import StringIO

str_match=r'"([^"\\]|\\[^"]|\\")*"'
single_var_param_match=r'(?:-?\d+|"(?:[^"\\]|\\[^"]|\\")*")'
call_param_match=r'(?:\(\)|\((?:' + single_var_param_match + r')(?:,' + single_var_param_match + r')*\))'
variable_match=r"\*?([a-zA-Z][a-zA-Z0-9_]*"+ call_param_match +r"?)(((\.|->)([a-zA-Z][a-zA-Z0-9_]*" + call_param_match + r"?))*)"

def interleave(*args):
    for idx in range(0, max(map(len,args))):
        for arg in args:
            try:
                yield arg[idx]
            except IndexError:
                continue

def output_declaration(s):
    global stack
    global file_name
    global line_number
    global declarations
    declarations.write('\t'*len(stack) + '#line %d "%s"' % (line_number,file_name)+'\n')
    declarations.write('\t'*len(stack) + s + '\n');

def output_definition(s):
    global stack
    global file_name
    global line_number
    global definitions
    definitions.write('\t'*(len(stack)-1) + '#line %d "%s"' % (line_number,file_name)+'\n')
    definitions.write('\t'*(len(stack)-1) + s + '\n');

def output_all(s):
    output_definition(s)
    output_declaration(s)

class tmpl_descr:
    def __init__(self,start,size):
        self.start_id=start
        self.param_num=size

class skin_block:
    basic_pattern='skin'
    basic_name='skin'
    pattern=r'^<%\s*skin\s+(\w+)?\s*%>$'
    type='skin'
    def use(self,m):
        global inline_cpp_to
        global namespace_name
        inline_cpp_to = output_declaration
        name = m.group(1)

        if namespace_name == '':
            if name == '':
                error_ext("Skin name is not defined implicitly or explicitly")
            else:
                namespace_name = name
        elif namespace_name != name and name:
            error_exit("Can't use more then one skin name for same skin: %s, %s" % ( namespace_name,name))
        output_all( "namespace %s {" % namespace_name)
        global stack
        stack.append(self)
    def on_end(self):
        global namespace_name
        output_all( "} // end of namespace %s" % namespace_name)


def write_class_loader(unsafe = False):
    global class_list
    global namespace_name
    output_definition("namespace {")
    output_definition(" cppcms::views::generator my_generator; ")
    output_definition(" struct loader { ")
    output_definition("  loader() { ")
    output_definition('   my_generator.name("%s");' % namespace_name)
    if  unsafe:
        safe = 'false'
    else:
        safe = 'true'
    for class_def in class_list:
        output_definition( '   my_generator.add_view<%s::%s,%s>("%s",%s);' \
                % (class_def.namespace,class_def.name,class_def.content_name,class_def.name,safe))
    output_definition('    cppcms::views::pool::instance().add(my_generator);')
    output_definition(' }')
    output_definition(' ~loader() {  cppcms::views::pool::instance().remove(my_generator); }')
    output_definition('} a_loader;')
    output_definition('} // anon ')


class html_type:
    basic_pattern='x?html'
    basic_name='xhtml'
    pattern=r'^<%\s*(x)?html\s*%>$'
    def use(self,m):
        global html_type_code
        if m.group(1):
            html_type_code='as_xhtml'
        else:
            html_type_code='as_html'


class view_block:
    pattern=r'^<%\s*view\s+(\w+)\s+uses\s+(:?:?\w+(::\w+)*)(\s+extends\s+(:?:?\w+(::\w+)?))?(?P<abs>\s+abstract)?(?P<inline>\s+inline)?\s*%>$'
    basic_pattern='view'
    basic_name='view'
    type='view'
    topmost = 0
    def declare(self):
        if self.extends=='' :
            constructor='cppcms::base_view(_s)'
            self.extends='cppcms::base_view'
            self.topmost = 1
        else:
            constructor='%s(_s,_content)' % self.extends;
        global dll_api
        if self.inline:
            api_ref = ''
        else:
            api_ref = dll_api
        output_declaration( "struct %s %s :public %s" % (api_ref, self.class_name , self.extends ))
        output_declaration( "{")
        if self.uses!='' : 
            output_declaration( "\t%s &content;" % self.uses)
            output_declaration( "\t%s(std::ostream &_s,%s &_content): %s,content(_content),_domain_id(0)" % ( self.class_name,self.uses,constructor ))
        else:
            output_declaration( "\t%s(std::ostream &_s): %s,_domain_id(0)" % ( self.class_name,constructor ))
        output_declaration("\t{")
        global spec_gettext
        if spec_gettext:
            self.gettext_domain = spec_gettext;
            output_declaration( '\t\t_domain_id=cppcms::translation_domain_scope::domain_id(_s,"%s");' % self.gettext_domain)
        else:
            output_declaration( '\t\t_domain_id=booster::locale::ios_info::get(_s).domain_id();')
            self.gettext_domain = None;
        output_declaration("\t}")

    def use(self,m):
        global view_created
        view_created = True
        self.abstract = m.group('abs')!=None
        self.inline = m.group('inline')!=None
        global view_name
        global output_template
        self.class_name=m.group(1)
        view_name = self.class_name
        self.uses=m.group(2)
        if m.group(4):
            self.extends=m.group(5)
        else:
            self.extends=''
        self.declare();
        global stack
        if len(stack)!=1 or stack[-1].type!='skin':
            error_exit("You must define view inside skin block only")
        stack.append(self)
        global namespace_name
        class information:
            content_name=self.uses
            name=self.class_name
            namespace=namespace_name
        global class_list
        if not self.abstract:
            class_list.append(information())
    def on_end(self):
        output_declaration( "private:")
        output_declaration( "\tint _domain_id;")
        output_declaration( "}; // end of class %s" % self.class_name)



class template_block:
    pattern=r'^<%\s*template\s+([a-zA-Z]\w*)\s*\(([\w\s,:\&]*)\)\s*(?P<abs>=\s*0\s*)?%>$'
    basic_pattern = 'template'
    basic_name='template'
    type='template'
    plist=[]
    def create_parameters(self,lst):
        pattern=r'^\s*((:?:?\w+(::\w+)*)\s*(const)?\s*(\&)?\s*(\w+))\s*(,(.*))?$'
        m=re.match(pattern,lst)
        res=[]
        while m:
            global tmpl_seq
            id=m.group(6)
            if id in tmpl_seq:
                error_exit("Duplicate definition of patameter %s" % id)
                for v in self.plist:
                    del tmpl_seq[v] 
                return ""
            tmpl_seq[id]=''
            res.append(m.group(1))
            self.plist.append(id)
            if m.group(8):
                lst=m.group(8)
                m=re.match(pattern,lst)
            else:
                return ','.join(res)
        for v in self.plist:
            del tmpl_seq[v]
        error_exit("Wrong expression %s" % lst)
        
    def use(self,m):
        global view_name
        global inline_templates
        self.name=m.group(1)
        params=""
        abstract = m.group('abs') != None
        if m.group(2) and not re.match('^\s*$',m.group(2)):
            params=self.create_parameters(m.group(2))
        if abstract:
            output_declaration( "virtual void %s(%s) = 0;" % (self.name,params) )
        else:
            if inline_templates:
                output_declaration( "virtual void %s(%s) {" % (self.name,params) )
                output_declaration( "\tcppcms::translation_domain_scope _trs(out(),_domain_id);\n")
            else:
                output_declaration( "virtual void %s(%s);" % (self.name,params) )
                output_definition( "void %s::%s(%s) {" % (view_name,self.name,params) )
                output_definition( "\tcppcms::translation_domain_scope _trs(out(),_domain_id);\n")
        global stack
        if len(stack)==0 or stack[-1].type!='view':
            error_exit("You must define template inside view block only")
        if abstract:
            return
        stack.append(self)
        global current_template
        current_template=self.name
        global ignore_inline
        global inline_cpp_to
        ignore_inline=0
        inline_cpp_to = output_template

    def on_end(self):
        global output_template
        output_template( "} // end of template %s" % self.name)
        global ignore_inline
        ignore_inline=1
        global tmpl_seq
        tmpl_seq={}
        global inline_cpp_to
        inline_cpp_to = output_declaration

        

def inline_content(s):
    global ignore_inline
    global output_template
    if not ignore_inline:
        output_template( 'out()<<"%s";' % to_string(s))

def warning(x):
    global file_name
    global line_number
    sys.stderr.write("Warning: %s in file %s, line %d\n" % (x,file_name,line_number))

def error_exit(x):
    global exit_flag
    global file_name
    global line_number
    sys.stderr.write("Error: %s in file %s, line %d\n" % (x,file_name,line_number))
    exit_flag=1

def to_string(s):
    res=''
    for c in s:
        global stack
        if c=='\n':
            res+="\\n\""+"\n"+"\t"*len(stack)+"\t\""
        elif c=="\t":
            res+="\\t"
        elif c=="\v":
            res+="\\v"
        elif c=="\b":
            res+="\\b"
        elif c=="\r":
            res+="\\r"
        elif c=="\f":
            res+="\\f"
        elif c=="\a":
            res+="\\a"
        elif c=="\\":
            res+="\\\\"
        elif c=="\"":
            res+="\\\""
        elif ord(c)>0 and ord(c)<32:
            res+="%03o" % ord(c)
        else:
            res+=c

    return res


def make_ident(val):
    m=re.match('^'+variable_match+'$',val)
    global tmpl_seq
    if m.group(1) in tmpl_seq:
        return val
    m2=re.match('^\*(.*)$',val)
    if m2:
        return "*content." + m2.group(1)
    else:
        return "content." + val

def print_using_block_start(class_name,variable_name,content_name,temp_and_view=None):
    global output_template
    if content_name:
        content=make_ident(content_name)
        guard=True
    else:
        content ='content'
        guard=False
    output_template(r'{')
    if guard:
        output_template(r'  cppcms::base_content::app_guard _g(%s,content);' % content);
    if temp_and_view:
        output_template(r'  cppcms::views::view_lock _vl(%s,out(),%s); %s &%s = _vl.use_view<%s>();' % ( temp_and_view, content, class_name, variable_name, class_name));
    else:
        output_template(r'  %s %s(out(),%s);' % ( class_name, variable_name, content));
    
def print_using_block_end():
    global output_template
    output_template('}')

class using_block:
    pattern=r'^<%\s*using\s+(?P<class>(?:\w+::)*\w+)(?:\s+with\s+(?P<content>' + variable_match + r'))?\s+as\s+(?P<name>[a-zA-Z_]\w*)'  \
            + r'(?P<from>\s+from' \
            + r'(\s*(?P<fst_str>'+ str_match +r')|(?:\s+(?P<fst_var>' + variable_match + r')))' \
            + r'(\s*,\s*((?P<snd_str>'+ str_match +r')|(?P<snd_var>' + variable_match + r')))?' \
            + r')?' \
        + '\s*%>$' 
    basic_pattern = 'using'
    basic_name = 'using'
    type='using'
    def use(self,m):
        if m.group('from'):
            temp_and_view = get_render_names(m);
        else:
            temp_and_view = None
        print_using_block_start(m.group('class'),m.group('name'),m.group('content'),temp_and_view)
        global stack
        stack.append(self)
    def on_end(self):
        print_using_block_end();


class foreach_block:
    pattern=r'^<%\s*foreach\s+([a-zA-Z]\w*)(\s+as\s+((:?:?\w+)(::\w+)*))?' \
        + r'(?:\s+rowid\s+([a-zA-Z]\w*)(?:\s+from\s+(\d+))?)?' \
        + r'(?:\s+(reverse))?' \
        + '\s+in\s+(' + variable_match +')\s*%>$'
    basic_pattern = 'foreach'
    basic_name = 'foreach'
    type='foreach'
    has_item=0
    has_separator=0
    separator_label=''
    on_first_label=''
    type_name=0
    def use(self,m):
        global output_template
        self.ident=m.group(1)
        self.seq_name=make_ident(m.group(9))
        self.rowid = m.group(6)
        if m.group(7):
            self.rowid_begin = int(m.group(7))
        else:
            self.rowid_begin = 0
        if m.group(8):
            self.reverse = 'r'
        else:
            self.reverse = ''
        self.type_name = m.group(3)
        global tmpl_seq
        if self.ident in tmpl_seq:
            error_exit("Nested sequences with same name %s" % self.ident)
        if self.rowid == self.ident:
            error_exit("Nested sequence and rowid has same name %s" % self.ident)
        if self.rowid and (self.rowid in tmpl_seq):
            error_exit("Nested sequences with same rowid name %s" % self.rowid )
        tmpl_seq[self.ident]='';
        output_template( "if((%s).%sbegin()!=(%s).%send()) {" % (self.seq_name,self.reverse,self.seq_name,self.reverse) )
        if self.rowid:
            tmpl_seq[self.rowid]='';
            output_template("    int %s = %s;" % (self.rowid,self.rowid_begin))
        global stack
        stack.append(self)

    def on_end(self):
        global output_template
        if not self.has_item:
            error_exit("foreach without item")

        global tmpl_seq
        del tmpl_seq[self.ident]
        if self.rowid:
            del tmpl_seq[self.rowid]

        output_template( "}" )
    def prepare_foreach(self):
        global output_template
        if not self.type_name:
            ptr_type = 'CPPCMS_TYPEOF((%(s)s).%(r)sbegin())'
        else:
            ptr_type = self.type_name
        incr = ''
        if self.rowid:
            incr = ',++%s' % self.rowid;
        fmt = "for("+ptr_type+" %(i)s_ptr=(%(s)s).%(r)sbegin(),%(i)s_ptr_end=(%(s)s).%(r)send();%(i)s_ptr!=%(i)s_ptr_end;++%(i)s_ptr%(u)s) {";
        fmt = fmt %  { 's' : self.seq_name, 'i' : self.ident , 'r' : self.reverse, 'u' : incr };
        output_template(fmt)
        if not self.type_name:
            output_template( "CPPCMS_TYPEOF(*%s_ptr) &%s=*%s_ptr;" % (self.ident,self.ident,self.ident))
        else:
            output_template( "std::iterator_traits< %s >::value_type &%s=*%s_ptr;" % (self.type_name,self.ident,self.ident))
        if self.has_separator:
            output_template( "if(%s_ptr!=(%s).%sbegin()) {" % (self.ident,self.seq_name,self.reverse))
        
        

class separator_block:
    pattern=r'^<%\s*separator\s*%>'
    basic_pattern = 'separator'
    basic_name = 'separator'
    type='separator'
    def use(self,m):
        global stack
        if len(stack)==0 or stack[len(stack)-1].type!='foreach':
            error_exit("separator without foreach")
            return
        foreachb=stack[len(stack)-1]
        if foreachb.has_separator:
            error_exit("two separators for one foreach")
        foreachb.has_separator=1
        foreachb.prepare_foreach()

        

class item_block:
    pattern=r'^<%\s*item\s*%>'
    basic_pattern = 'item'
    basic_name = 'item'
    type='item'
    def use(self,m):
        global stack
        global output_template
        if not stack or stack[-1].type!='foreach':
            error_exit("item without foreach")
            return
        foreachb=stack[-1]
        if foreachb.has_item:
            error_exit("Two items for one foreach");
        if foreachb.has_separator:
            output_template( "} // end of separator")
        else:
            foreachb.prepare_foreach()
        foreachb.has_item=1
        stack.append(self)
    def on_end(self):
        global output_template
        output_template( "} // end of item" )

class empty_block:
    pattern=r'^<%\s*empty\s*%>'
    basic_pattern = 'empty'
    basic_name = 'empty'
    type='empty'
    def use(self,m):
        global stack
        global output_template
        if not stack or stack[-1].type!='foreach':
            error_exit("empty without foreach")
            return
        forb=stack.pop()
        if not forb.has_item:
            error_exit("Unexpected empty - item missed?")
        output_template( " } else {")
        self.ident=forb.ident
        self.rowid=forb.rowid
        stack.append(self)
    def on_end(self):
        global output_template
        output_template( "} // end of empty")
        global tmpl_seq
        del tmpl_seq[self.ident]
        if self.rowid:
            del tmpl_seq[self.rowid]


class else_block:
    pattern=r'^<%\s*else\s*%>$'
    basic_pattern = 'else'
    basic_name = 'else'
    type='else'
    def on_end(self):
        global output_template
        output_template("}")
    def use(self,m):
        global output_template
        prev=stack.pop()
        if prev.type!='if' and prev.type!='elif':
            error_exit("elif without if");
        output_template( "}else{")
        stack.append(self)

class if_block:
    pattern=r'^<%\s*(if|elif)\s+((not\s+|not\s+empty\s+|empty\s+)?('+variable_match+')|\((.+)\)|)\s*%>$'
    basic_pattern = '(if|elif)'
    basic_name = 'if/elif'
    type='if'
    def prepare(self):
        global output_template
        output_template( "if(%s) {" % self.ident)

    def on_end(self):
        global output_template
        output_template( "} // endif")

    def use(self,m):
        global stack
        global output_template
        self.type=m.group(1)
        if m.group(4):
            if m.group(4)=='rtl':
                self.ident='(cppcms::locale::translate("LTR").str(out().getloc())=="RTL")'
            else:
                self.ident=make_ident(m.group(4))
            if m.group(3):
                if re.match('.*empty',m.group(3)):
                    self.ident=self.ident + '.empty()'
                if re.match('not.*',m.group(3)):
                    self.ident="!("+self.ident+")"
        else:
            self.ident=m.group(10)
        if self.type == 'if' :
            self.prepare()
            stack.append(self)
        else: # type == elif
            if stack :
                prev=stack.pop()
                if prev.type!='if' and prev.type!='elif':
                    error_exit("elif without if");
                output_template( "}")
                output_template( "else")
                self.prepare()
                stack.append(self)
            else:
                error_exit("Unexpeced elif");
# END ifop                
            

class end_block:
    pattern=r'^<%\s*end(\s+(\w+))?\s*%>$';
    basic_pattern = 'end'
    basic_name = 'end'
    def use(self,m):
        global stack
        if not stack:
            error_exit("Unexpeced 'end'");
        else:
            obj=stack.pop();
            if m.group(1):
                if obj.type!=m.group(2):
                    error_exit("End of %s does not match block %s" % (m.group(2) , obj.type));
            obj.on_end()

class error_com:
    pattern=r'^<%(.*)%>$'
    basic_pattern = ''
    basic_name = ''
    def use(self,m):
        error_exit("Invalid statement `%s'" % m.group(1))


class domain_block:
    pattern=r'^<%\s*domain\s+(\w+)\s*%>$'
    basic_pattern = 'domain'
    basic_name = 'domain'
    type = 'domain'
    def use(self,m):
        gt = m.group(1)
        global spec_gettext
        global view_created
        if not spec_gettext:
            if view_created:
                error_exit("Can't use domain command after a view was created")
            else:
                spec_gettext = gt
            return
        if spec_gettext != gt:
            error_exit("Gettext domain is already defined as `%s' and differs from given `%s'" % (spec_gettext , gt ))

class cpp_include_block:
    pattern=r'^<%\s*c\+\+(src)?\s+(.*)%>$'
    basic_pattern = 'c\+\+(src)?'
    basic_name = 'c++'
    def use(self,m):
        global inline_cpp_to
        if m.group(1):
            output_definition(m.group(2));
        else:
            inline_cpp_to( m.group(2));

def get_filter(cur):
    if not cur:
        global scope_filter
        return scope_filter
    return cur

class base_show:
    mark='('+variable_match+r')\s*(\|(.*))?'
    base_pattern='^\s*'+mark + '$'
    def __init__(self,default_filter=None):
        self.default_filter=default_filter
    def get_params(self,s):
        pattern='^\s*(('+variable_match+')|('+str_match+')|(\-?\d+(\.\d*)?))\s*(,(.*))?$'
        res=[]
        m=re.match(pattern,s)
        while m:
            if m.group(2):
                res.append(make_ident(m.group(2)))
            elif m.group(8):
                res.append(m.group(8))
            elif m.group(10):
                res.append(m.group(10))
            if m.group(13):
                s=m.group(13)
                m=re.match(pattern,s)
            else:
                return res
        error_exit("Invalid parameters: `%s'" % s )
        return []
    def prepare(self,s):
        m=re.match(self.base_pattern,s)
        if not m:
            error_exit("No variable")
            return [];
        var=make_ident(m.group(1))
        if not m.group(8):
            return "%s(%s)" % (get_filter(self.default_filter), var)
        filters=m.group(8)
        expr='^\s*(ext\s+)?(\w+)\s*(\((([^"\)]|'+str_match + ')*)\))?\s*(\|(.*))?$'
        m=re.match(expr,filters)
        while m:
            if m.group(1):
                func="content."+m.group(2)
            else:
                func="cppcms::filters::" + m.group(2)
            if m.group(3):
                params=','.join([var]+self.get_params(m.group(4)))
            else:
                params=var
            var=func+"("+params+")"
            if m.group(8):
                filters=m.group(8)
                m=re.match(expr,filters)
            else:
                return var
        error_exit("Seems to be a problem in expression %s" % filters)
        return "";

class form_block:
    pattern=r'^<%\s*form\s+(as_p|as_table|as_ul|as_dl|as_space|input|block|begin|end)\s+('\
         + variable_match +')\s*%>$'
    
    basic_pattern  = 'form'
    basic_name = 'form'
    type = 'form'

    def format_input(self,command_type,ident):
   
        global html_type_code
        global output_template

        flags = 'cppcms::form_flags::' + html_type_code;
        output_template('{ cppcms::form_context _form_context(out(),%s);' % flags)
        render_command = '    (%s).render_input(_form_context);' % ident;

        if command_type=='begin':
            output_template('    _form_context.widget_part(cppcms::form_context::first_part);')
            output_template(render_command)
        elif command_type=='end':
            output_template('    _form_context.widget_part(cppcms::form_context::second_part);')
            output_template(render_command)
        else:
            output_template('    _form_context.widget_part(cppcms::form_context::first_part);')
            output_template(render_command)
            output_template('    out() << (%s).attributes_string();' % ident)
            output_template('    _form_context.widget_part(cppcms::form_context::second_part);')
            output_template(render_command)
        output_template('}')
    
    def use(self,m):
        global output_template

        ident=make_ident(m.group(2))
        command_type = m.group(1)
        global html_type_code
        if command_type=='input' or command_type=='begin' or command_type=='end' or command_type=='block':
            if command_type != 'block':
                self.format_input(command_type,ident)
            else:
                self.format_input('begin',ident)
                self.ident = ident
                self.command_type = 'end'
                global stack
                stack.append(self)

        else:
            flags = 'cppcms::form_flags::%s,cppcms::form_flags::%s' % ( html_type_code, m.group(1));
            output_template('{ cppcms::form_context _form_context(out(),%s); (%s).render(_form_context); }' % (flags , ident))

    def on_end(self):
        self.format_input(self.command_type,self.ident)

def get_render_names(m):
    first_str = m.group('fst_str')
    first_var = m.group('fst_var')
    if first_var:
        first = make_ident(first_var)
    else:
        first = first_str
    
    second_str = m.group('snd_str')
    second_var = m.group('snd_var')
    if second_var:
        second = make_ident(second_var)
    else:
        second = second_str

    if first and second:
        template_name = first
        view_name = second
    else:
        global namespace_name
        template_name = '"' + namespace_name + '"'
        view_name = first;
    return template_name + ', ' + view_name
    

class render_block:
    pattern=r'^<%\s*render\s+' \
            + r'((?P<fst_str>'+ str_match +r')|(?P<fst_var>' + variable_match + r'))' \
            + r'(\s*,\s*((?P<snd_str>'+ str_match +r')|(?P<snd_var>' + variable_match + r')))?' \
            + r'(\s+with\s+(?P<content>' + variable_match + r'))?\s*%>$'
    basic_pattern = 'render'
    basic_name = 'render'
    def use(self,m):
        global output_template
        if m.group('content'):
            content = make_ident(m.group('content'))
            guard=True
        else:
            content = 'content';
            guard=False
        
        temp_and_view = get_render_names(m);
       
        output_template('{')

        if guard:
            output_template(r'cppcms::base_content::app_guard _g(%s,content);' % content)

        output_template(r'cppcms::views::pool::instance().render(%s,out(),%s);' % (temp_and_view,content))

        output_template('}')


class filters_show_block(base_show):
    pattern=r'^<%(=)?\s*('+ variable_match + r'\s*(\|.*)?)%>$'
    basic_pattern = '=?'
    basic_name = 'Inline Variable'
    def use(self,m):
        global output_template
        if not m.group(1):
            warning("Variables syntax like <% foo %> is deprecated, use <%= foo %> syntax");
        expr=self.prepare(m.group(2));
        if expr!="":
            output_template('out()<<%s;' % expr)

def make_format_params(s,default_filter = None):
    pattern=r'^(([^,\("]|'+str_match+'|\(([^"\)]|'+str_match+')*\))+)(,(.*))?$'
    params=[]
    m=re.match(pattern,s)
    s_orig=s
    while m.group(1):
        res=base_show(default_filter).prepare(m.group(1))
        if res:
            params.append(res)
        if not m.group(6):
            return params
        s=m.group(7)
        m=re.match(pattern,s)
    error_exit("Seems to be wrong parameters list [%s]" % s_orig)
    return []

class filter_block:
    pattern=r'^<%\s*filter\s+(ext\s+)?(\w+)\s*%>'
    basic_pattern = 'filter'
    basic_name = 'filter'
    type = 'filter'
    def use(self,m):
        global scope_filter
        self.save_filter = scope_filter
        if m.group(1):
            scope_filter='content.' + m.group(2)
        else:
            scope_filter='cppcms::filters::' + m.group(2)
        global stack
        stack.append(self)
    def on_end(self):
        global scope_filter
        scope_filter=self.save_filter

class cache_block:
    pattern=r'^<%\s*cache\s+((?P<str>'+ \
            str_match +')|(?P<var>'+ variable_match +r'))' + \
            r'(\s+for\s+(?P<time>\d+))?(\s+on\s+miss\s+(?P<callback>[a-zA-Z]\w*)\(\))?' \
            + r'(?P<notriggers>\s+no\s+triggers)?' \
            + r'(?P<norecording>\s+no\s+recording)?' \
            + '\s*%>$'        
    basic_pattern = 'cache'
    basic_name = 'cache'
    type = 'cache'
    def use(self,m):
        global output_template
        if(m.group('str')):
            self.parameter = m.group('str')
        else:
            self.parameter = make_ident(m.group('var'));
        self.notriggers = m.group('notriggers')
        self.norecording = m.group('norecording')
        output_template('{ std::string _cppcms_temp_val;')
        output_template('  if(content.app().cache().fetch_frame(%s,_cppcms_temp_val))' % self.parameter);
        output_template('      out() << _cppcms_temp_val;');
        output_template('  else {')
        output_template('    cppcms::copy_filter _cppcms_cache_flt(out());')
        if not self.norecording:
            output_template('    cppcms::triggers_recorder _cppcms_trig_rec(content.app().cache());')
        # the code below should be the last one 
        if(m.group('callback')):
            output_template('    '+make_ident(m.group('callback')+'()') + ';')
        self.timeout = m.group('time');
        global stack
        stack.append(self)
    def on_end(self):
        global output_template
        if self.timeout:
            timeout_time = self.timeout
        else:
            timeout_time = '-1'
        if self.norecording:
            recorded = 'std::set<std::string>()'
        else:
            recorded = '_cppcms_trig_rec.detach()'
        if self.notriggers:
            notriggers='true'
        else:
            notriggers='false'
        output_template('    content.app().cache().store_frame(%s,_cppcms_cache_flt.detach(),%s,%s,%s);' \
                    % (self.parameter,recorded,timeout_time,notriggers))
        output_template('}} // cache')

class trigger_block:
    pattern=r'^<%\s*trigger\s+((?P<str>'+  str_match +')|(?P<var>'+ variable_match +r'))' + r'\s*%>$'
    basic_pattern = 'trigger'
    basic_name = 'trigger'
    def use(self,m):
        global output_template
        if(m.group('str')):
            parameter = m.group('str')
        else:
            parameter = make_ident(m.group('var'));
        output_template('content.app().cache().add_trigger(%s);' % parameter)




class ngettext_block:
    pattern=r'^<%\s*ngt\s*((?:' + str_match + '\s*,\s*)?'+str_match+')\s*,\s*('+str_match+')\s*,\s*('+variable_match+')\s*(using(.*))?\s*%>$'
    basic_pattern = 'ngt'
    basic_name = 'ngt'
    def use(self,m):
        global output_template
        s1=m.group(1)
        s2=m.group(4)
        idt=make_ident(m.group(6))
        params=[]
        if m.group(12):
            params=make_format_params(m.group(13))
        if not params:
            output_template( "out()<<cppcms::locale::translate(%s,%s,%s);" % (s1,s2,idt))
        else:
            output_template( "out()<<cppcms::locale::format(cppcms::locale::translate(%s,%s,%s)) %% (%s);" % (s1,s2,idt, ') % ('.join(params)))
            

class gettext_block:
    pattern=r'^<%\s*gt\s*((?:' + str_match + '\s*,\s*)?'  +str_match+')\s*(using(.*))?\s*%>$'
    basic_pattern = 'gt'
    basic_name = 'gt'
    def use(self,m):
        global output_template
        s=m.group(1)
        params=[]
        if m.group(4):
            params=make_format_params(m.group(5))
        if not params:
            output_template( "out()<<cppcms::locale::translate(%s);" % s)
        else:
            output_template( "out()<<cppcms::locale::format(cppcms::locale::translate(%s)) %% (%s);" % (s , ') % ('.join(params)))

class url_block:
    pattern=r'^<%\s*url\s*('+str_match+')\s*(using(.*))?\s*%>$'
    basic_pattern = 'url'
    basic_name = 'url'
    def use(self,m):
        global output_template
        s=m.group(1)
        params=[]
        if m.group(3):
            params=make_format_params(m.group(4),'cppcms::filters::urlencode')
        if not params:
            output_template( "content.app().mapper().map(out(),%s);" % s)
        else:
            output_template( "content.app().mapper().map(out(),%s, %s);" % (s , ', '.join(params)))

class csrf_block:
    pattern=r'^<%\s*csrf(\s+(token|cookie|script))?\s*%>$'
    basic_pattern = 'csrf'
    basic_name = 'csrf'
    def use(self,m):
        global output_template
        s=m.group(2)

        global html_type_code

        if html_type_code == 'as_xhtml':
            suffix = '/'
        else:
            suffix =''

        if not s:
            output_template(r'out() << "<input type=\"hidden\" name=\"_csrf\" value=\"" << content.app().session().get_csrf_token() <<"\" %s>\n";' % suffix)
        elif s == 'token':
            output_template(r'out() << content.app().session().get_csrf_token();')
        elif s == 'cookie':
            output_template(r'out() << content.app().session().get_csrf_token_cookie_name();')
        else: # script
            script="""
            <script type='text/javascript'>
            <!--
                {
                    var cppcms_cs = document.cookie.indexOf("$=");
                    if(cppcms_cs != -1) {
                        cppcms_cs += '$='.length;
                        var cppcms_ce = document.cookie.indexOf(";",cppcms_cs);
                        if(cppcms_ce == -1) {
                            cppcms_ce = document.cookie.length;
                        }
                        var cppcms_token = document.cookie.substring(cppcms_cs,cppcms_ce);
                        document.write('<input type="hidden" name="_csrf" value="' + cppcms_token + '" %s>');
                    }
                }
            -->
            </script>
            """ % suffix; 
            script = to_string(script).replace('$','"<< content.app().session().get_csrf_token_cookie_name() <<"')
            output_template('out() << "' + script +'";')


class include_block:
    basic_pattern = 'include'
    basic_name = 'include'
    pattern=r'^<%\s*include\s+([a-zA-Z]\w*(::\w+)?)\s*\(\s*(.*)\)' \
            + r'(?:\s+' \
            +   r'(from\s+(?P<from>\w+)' \
            +    '|' \
            +   r'using\s+(?P<class>(\w+::)*(\w+))(?:\s+with\s+(?P<content>' + variable_match +r'))?' \
            + r'))?' \
            + r'\s*%>$'

    def print_include(self,call,params):
        global output_template
        output_template( "%s(%s);" % (call , ','.join(params)))
        
    def use(self,m):
        if m.group(3):
            params=base_show().get_params(m.group(3))
        else:
            params=[]
        call=m.group(1)
        if m.group('from'):
            call = m.group('from') + '.' + call
            self.print_include(call,params)
        elif m.group('class'):
            print_using_block_start(m.group('class'),'_using',m.group('content'))
            self.print_include('_using.' + call,params)
            print_using_block_end()
        else:
            self.print_include(call,params)


def fetch_content(content):
    tmp=''
    for row in re.split('\n',content):
        global line_number
        global file_name
        line_number+=1
        l1=re.split(r'<%([^"%]|"([^"\\]|\\[^"]|\\")*"|%[^>])*%>',row)
        n=0
        for l2 in re.finditer(r'<%([^"%]|"([^"\\]|\\[^"]|\\")*"|%[^>])*%>',row):
            yield tmp+l1[n]
            tmp=''
            yield l2.group(0)
            n+=3
        tmp+=l1[n]+'\n'
    yield tmp

def help():
    print( "Usage cppcms_tmpl_cc [-o filename.cpp] [-s skin] [-d domain] file1.tmpl ... \n" \
        "      -o/--code filename.cpp        file name that implements this template\n" \
        "      -s/-n/--skin skin             define skin name\n" \
        "      -d domain                     setup gettext domain for this template\n" \
        "      -u/--unsafe-cast              use unsafe static casting instead of dynamic casing for dlls\n" \
        "      -l/--no-loader                do not generate loader for the views.\n" \
        "                                    This requires a separate loader to be implemented in some other cpp.\n" \
        "      -H/--header filename.hpp      generate header file. \n" \
        "      -I/--include directory        prepend directory to file name include path. \n" \
        "      -i/--inline-templates value   Whether to inline the template definitions inside the view declaration.\n" \
        "                                    value can be one of the following:\n" \
        "               true                 Inline the template functions inside the view class declaration.\n" \
        "               false                Place the template function definitions outside the class declaration.\n" \
        "               default              (Default value is parameter is omitted.) If header file is\n" \
        "                                    generated, same as false, otherwise same as true.\n" \
        "      -h/--help                     show this help message\n")

def main():
    global stack
    all=[]
    indx=1
    global namespace_name
    global output_file
    global header_file
    global exit_flag
    global include_directory
    global inline_templates
    unsafe_build = False
    write_loader = True
    while indx < len(os.sys.argv):
        if os.sys.argv[indx]=='-s' or os.sys.argv[indx]=='-n' or os.sys.argv[indx]=='--skin':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("%s should be followed by skin name\n" % (os.sys.argv[indx]))
                help()
                exit_flag=1
                return
            else:
                namespace_name=os.sys.argv[indx+1];
                indx+=1
        elif os.sys.argv[indx]=='-o' or os.sys.argv[indx]=='--code':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("%s should be followed by output file name\n" % (os.sys.argv[indx]))
                help()
                exit_flag=1
                return
            else:
                output_file=os.sys.argv[indx+1]
                indx+=1
        elif os.sys.argv[indx]=='-I' or os.sys.argv[indx]=='-include':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("%s should be followed by directory name\n" % (os.sys.argv[indx]))
                help()
                exit_flag=1
                return
            else:
                include_directory=os.sys.argv[indx+1]
                if not include_directory.endswith('/') and not include_directory.endswith('\\'):
                    include_directory=include_directory + '/';
                indx+=1
        elif os.sys.argv[indx]=='-H' or os.sys.argv[indx]=='--header':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("%s should be followed by output header file name\n" % (os.sys.argv[indx]))
                help()
                exit_flag=1
                return
            else:
                header_file=os.sys.argv[indx+1]
                indx+=1
        elif os.sys.argv[indx]=='-i' or os.sys.argv[indx]=='--inline-templates':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("%s should be followed by inline value.\n" % (os.sys.argv[indx]))
                help()
                exit_flag=1
                return
            else:
                inline_templates=os.sys.argv[indx+1]
                indx+=1
        elif os.sys.argv[indx]=='-d':
            if indx+1>=len(os.sys.argv):
                sys.stderr.write("-d should followed by gettext domain name\n")
                help()
                exit_flag=1
                return
            else:
                global spec_gettext
                spec_gettext=os.sys.argv[indx+1]
                indx+=1
        elif os.sys.argv[indx]=='-u' or os.sys.argv[indx]=='--unsafe-cast':
            unsafe_build = True
        elif os.sys.argv[indx]=='-l' or os.sys.argv[indx]=='--no-loader':
            write_loader = False
        elif os.sys.argv[indx]=='--help' or os.sys.argv[indx]=='-h':
            help()
            exit_flag=1
            return
        else:
            all.append(os.sys.argv[indx])
        indx+=1
    if not all:
        sys.stderr.write("No input file names given\n")
        help()
        exit_flag=1
        return
    if inline_templates == "default":
        if header_file!='':
            inline_templates=False
        else:
            inline_templates=True
    elif inline_templates == "true":
        inline_templates = True
    else:
        inline_templates = False
    global output_template
    if inline_templates:
        output_template = output_declaration
    else:
        output_template = output_definition

    if header_file!='':
        global header_define 
        global dll_api
        header_define = "CPPCMS_GENERATED_HEADER_%s_TMPL_HEADER_INCLUDED" % ( re.sub("[^a-zA-Z0-9]+", "_", header_file ).upper())
        if sys.version_info >= (2,5):
            from hashlib import md5
        else:
            from md5 import md5
        dll_api = 'VIEW_%s_API' % md5(header_define).hexdigest().upper()
        
    global output_fd
    if output_file!='':
        output_fd=open(output_file,"w")
    for file in all:
        global file_name
        global line_number
        global inline_cpp_to
        inline_cpp_to = output_declaration
        line_number=0
        file_name=file
        f=open(file,'r')
        content=f.read()
        f.close()
        for x in fetch_content(content):
            if x=='' : continue
            if len(stack)==0:
                if re.match(r"^\s*$",x):
                    continue
                elif not re.match(r"<\%.*\%>",x):
                    error_exit("Content is not allowed outside template blocks")
                    continue
            matched=0
            for c in [\
                    skin_block(), \
                    view_block(), \
                    template_block(), \
                    end_block(), \
                    if_block(), \
                    else_block(), \
                    cpp_include_block(), \
                    gettext_block(),ngettext_block(), \
                    url_block(), \
                    foreach_block(), item_block(), empty_block(),separator_block(), \
                    include_block(), \
                    cache_block(), \
                    trigger_block(), \
                    filter_block(), \
                    using_block(), \
                    render_block(), \
                    html_type(), form_block(), csrf_block(), \
                    domain_block(), \
                    filters_show_block(), error_com() ]:

                basic_pattern = r'^<%\s*' + c.basic_pattern + r'.*%>$'
                if re.match(basic_pattern,x):
                    m = re.match(c.pattern,x)
                    if m:
                        c.use(m)
                    else:
                        error_exit('Syntax error in command %s : %s' % ( c.basic_name , x))
                    matched=1
                    break;
            if not matched:
                inline_content(x)


        if stack:
            error_exit("Unexpected end of file %s" % file)
    global class_list
    if class_list and exit_flag==0 and write_loader:
        write_class_loader(unsafe_build)

#######################
# MAIN
#######################


html_type_code='as_html'
output_file=''
header_file=''
include_directory=''
output_fd=sys.stdout
namespace_name=''
file_name=''
labels_counter=0
tmpl_seq={}
template_parameters={}
templates_map={}
parameters_counter=2
stack=[]
class_list=[]
exit_flag=0
current_template=''
spec_gettext=''
ignore_inline=1
view_created=False
scope_filter='cppcms::filters::escape'

view_name = ''
declarations = StringIO.StringIO();
definitions = StringIO.StringIO();
inline_cpp_to = output_declaration
inline_templates = "default"
output_template = output_definition
header_define = ''
dll_api = ''


################
main()
################

if header_file!='':
    output_hfd=open(header_file,"w")
    output_hfd.write("#ifndef %s\n" % ( header_define ))
    output_hfd.write("#define %s\n\n" % ( header_define ))
    output_hfd.write("#if defined(__WIN32) || defined(_WIN32) || defined(WIN32) || defined(__CYGWIN__)\n")
    output_hfd.write("#  ifdef DLL_EXPORT\n")
    output_hfd.write("#    ifdef %s_SOURCE\n" % dll_api)
    output_hfd.write("#      define %s __declspec(dllexport)\n" % dll_api)
    output_hfd.write("#    else\n")
    output_hfd.write("#      define %s __declspec(dllimport)\n" % dll_api)
    output_hfd.write("#    endif\n")
    output_hfd.write("#  else\n")
    output_hfd.write("#    define %s\n" % dll_api)
    output_hfd.write("#  endif\n")
    output_hfd.write("#else\n")
    output_hfd.write("#  define %s\n" % dll_api)
    output_hfd.write("#endif\n")
    output_hfd.write(declarations.getvalue());
    output_hfd.write("#endif // %s\n" % ( header_define ))
    output_hfd.close()
    output_fd.write('#define %s_SOURCE\n' % dll_api);
    output_fd.write('#include "%s"\n\n' %  os.path.basename(header_file));
else:
    output_fd.write(declarations.getvalue());

output_fd.write(definitions.getvalue());

if output_fd!=sys.stderr:
    output_fd.close()

if exit_flag!=0 and output_file!='':
    try:
        os.unlink(output_file)
    except:
        pass

sys.exit(exit_flag)


# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
