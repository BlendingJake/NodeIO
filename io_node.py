bl_info = {
    "name": "NodeIO",
    "author": "Jacob Morris",
    "version": (0, 1),
    "blender": (2, 78, 0),
    "location": "Node Editor > Properties",
    "description": "Allows The Exporting And Importing Of Node Trees Via .bnodes Files",
    "category": "Import-Export"
    }

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty
from datetime import datetime
from time import tzname
import operator
from inspect import getmembers
from os import path, mkdir, listdir, walk, remove as remove_file, sep as os_file_sep
from shutil import copyfile, rmtree
import zipfile
from mathutils import *
import json

version_number = (0, 1)
DEBUG_FILE = True  # makes JSON file more human readable at the cost of file-size
ROUND = 4


def make_list(data):
    out = []
    for i in data:
        if isinstance(i, (bool, str)):
            out.append(i)
        else:  # int, float
            out.append(round(i, ROUND))
    return out


def collect_node_data(n: bpy.types.Node):
    ns, inputs, outputs, dependencies = [], [], [], []
    is_group = True if n.type == "GROUP" else False

    # certain nodes that do not support some operations, like having no .inputs or .outputs,
    node_exclude_list = ['NodeReroute', 'NodeGroupInput', 'NodeGroupOutput']
    socket_field_list = ['default_value', "value", "objectName", "fontName", "category", "groupName", "textBlockName",
                         "sequenceName", 'isUsed', 'easeIn', 'easeOut']

    # types that can be converted to lists
    list_types = (Color, Vector, Euler, Quaternion, bpy.types.bpy_prop_array)

    if n.bl_idname not in node_exclude_list:  # Reroute does have in and out, but does not know type until linked
        # inputs
        for j in range(len(n.inputs)):
            socket = n.inputs[j]
            data = {"index": j, "bl_idname": socket.bl_idname, 'values': {}}
            for i in socket_field_list:
                try:
                    val = eval("socket.{}".format(i))
                    if isinstance(val, list_types):  # list
                        data["values"][i] = make_list(val)
                    elif isinstance(val, (str, bool)):
                        data["values"][i] = val
                    elif isinstance(val, (float, int)):
                        data["values"][i] = round(val, ROUND)
                except AttributeError:
                    pass

            if data['values']:
                inputs.append(data)

        # outputs
        for j in range(len(n.outputs)):
            socket = n.outputs[j]
            data = {"index": j, "bl_idname": socket.bl_idname, 'values': {}}
            for i in socket_field_list:
                try:
                    val = eval("socket.{}".format(i))
                    if isinstance(val, list_types):  # list
                        data["values"][i] = make_list(val)
                    elif isinstance(val, (str, bool)):
                        data["values"][i] = val
                    elif isinstance(val, (float, int)):
                        data["values"][i] = round(val, ROUND)
                except AttributeError:
                    pass

            if data['values']:
                outputs.append(data)
    elif n.bl_idname == "NodeGroupInput":
        temp = []
        for i in n.inputs:
            temp.append(i.bl_idname)
            temp.append(i.name)
        ns += ["group_input", temp]
    elif n.bl_idname == "NodeGroupOutput":
        temp = []
        for i in n.outputs:
            temp.append(i.bl_idname)
            temp.append(i.name)
        ns += ["group_output", temp]

    # list of default values to ignore for smaller file-size, or because not needed, also if property is read-only
    exclude_list = ['__doc__', '__module__', '__slots__', 'bl_description', 'bl_height_default', 'bl_height_max',
                    'bl_height_min', 'bl_icon', 'bl_rna', 'bl_static_type', 'bl_width_default', 'bl_width_min',
                    'bl_width_max', 'color_mapping', 'draw_buttons', 'draw_buttons_ext', 'image_user', 'input_template',
                    'inputs', 'internal_links', 'is_registered_node_type', 'bl_label', 'output_template', 'outputs',
                    'poll', 'poll_instance', 'rna_type', 'shading_compatibility', 'show_options', 'show_preview',
                    'show_texture', 'socket_value_update', 'texture_mapping', 'type', 'update', 'viewLocation',
                    'width_hidden', 'bl_idname', 'dimensions', 'isAnimationNode', 'evaluationExpression',
                    'socketIdentifier', 'canCache', 'iterateThroughLists', 'identifier']
    exclude = {}  # for checking item membership, dict is faster then list
    for i in exclude_list:
        exclude[i] = i

    for method in getmembers(n):
        if method[0] not in exclude:
            t = method[1]
            val = eval("n.{}".format(method[0]))  # get value

            # special handling for certain types
            if isinstance(t, list_types):  # TUPLE
                ns += [method[0], make_list(val)]
            elif isinstance(t, (bpy.types.CurveMapping, bpy.types.ShaderNodeRGBCurve)):  # CURVES
                if isinstance(t, bpy.types.CurveMapping):
                    c = n
                else:  # happens with n_InterpolationFromCurveMappingNode, has ShaderNodeRGBCurve which has curve
                    c = n.curveNode
                curves = [make_list(c.mapping.black_level), make_list(c.mapping.white_level),
                          str(c.mapping.clip_max_x), str(c.mapping.clip_max_y), str(c.mapping.clip_min_x),
                          str(c.mapping.clip_min_y), str(c.mapping.use_clip)]

                for curve in c.mapping.curves:
                    points = [curve.extend]
                    for point in curve.points:
                        points.append([make_list(point.location), point.handle_type])
                    curves.append(points)
                ns += ["mapping", curves]
            elif isinstance(t, bpy.types.ColorRamp):  # COLOR RAMP
                els = []
                for j in n.color_ramp.elements:
                    cur_el = [j.position, make_list(j.color)]
                    els.append(cur_el)
                ns += ["color_ramp.color_mode", n.color_ramp.color_mode, "color_ramp.interpolation",
                       n.color_ramp.interpolation, "color_ramp.elements", els]
            elif isinstance(t, bpy.types.NodeTree):  # NODE TREE
                ns += ["node_tree.name", val.name]
            elif isinstance(t, bpy.types.Image) and n.image is not None:  # IMAGE
                ns += ["image", n.image.name]
                dependencies.append(['image', n.image.name, n.image.filepath])
            elif isinstance(t, bpy.types.ParticleSystem):  # PARTICLE SYSTEM - needs objects and particle system
                ns += [method[0], [n.object, val.name]]
            elif isinstance(t, (str, bool)):  # STRING
                ns += [method[0], val]
            elif isinstance(t, (int, float)):  # FlOAT, INTEGER
                ns += [method[0], round(val, ROUND)]
            elif isinstance(t, bpy.types.Node):  # FRAME NODE
                ns += [method[0], val.name]

    # extra information needed for creating nodes
    if n.bl_idname == 'an_CreateListNode':  # have to determine number of inputs, has to be evaluated after assignedType
        ns += ['an_list_size', len(n.inputs) - 1]

    return [{"inputs": inputs, "outputs": outputs, "node_specific": ns, "bl_idname": n.bl_idname}, is_group,
            dependencies]


# recursive method that collects all nodes and if group node goes and collects its nodes
# data is added to data in [[nodes, links], [nodes, links]] group by group
def collect_nodes(nodes, links, dependencies, names, name, data):
    m_n = []
    m_l = []
    
    for n in nodes:  # nodes
        out, is_group, im = collect_node_data(n)
        m_n.append(out)
        dependencies.append(im)
        
        if is_group:
            collect_nodes(n.node_tree.nodes, n.node_tree.links, dependencies, names, n.node_tree.name, data)
        
    for l in links:  # links
        out = link_info(l)
        m_l.append(out)
        
    data.append([m_n, m_l])   
    names[name] = len(data) - 1 


def link_info(link):
    out = [link.from_node.name]

    fr = link.from_socket.path_from_id()
    fr = fr.split(".")

    if len(fr) == 3:
        fr = fr[2]
    else:
        fr = fr[1]

    n1 = fr.index("[")
    n2 = fr.index("]")
    ind = int(fr[n1 + 1:n2])
    out.append(ind)
    out.append(link.to_node.name)
    fr = link.to_socket.path_from_id()
    fr = fr.split(".")

    if len(fr) == 3:
        fr = fr[2]
    else:
        fr = fr[1]

    n1 = fr.index("[")
    n2 = fr.index("]")
    ind = int(fr[n1 + 1:n2])
    out.append(ind)

    return out


def export_node_tree(self, context):
    to_export = []
    # export_type = context.scene.node_io_export_type
    export_path = bpy.path.abspath(context.scene.node_io_export_path)
    folder_path = None
    folder_name = None
    node_tree = context.space_data.node_tree

    # check data
    if not export_path:
        self.report({"ERROR"}, "Empty Export Path")
        return
    elif not path.exists(export_path):
        self.report({"ERROR"}, "Export Path '{}' Does Not Exist".format(export_path))
        return
    elif node_tree is None:
        self.report({"ERROR"}, "No Active Node Tree")

    # COLLECT NEED INFORMATION: to_export allows multiple node_trees at a time. Info formatted into dict
    # {"nodes":____, "links":____, "name":____, "bl_idname":_____}
    if node_tree.bl_idname in ("ShaderNodeTree", "MitsubaShaderNodeTree"):
        to_export.append({"nodes": node_tree.nodes, "links": node_tree.links, "name":
                         context.active_object.active_material.name, "bl_idname": node_tree.bl_idname})
    elif node_tree.bl_idname == "an_AnimationNodeTree":
        to_export.append({"nodes": node_tree.nodes, "links": node_tree.links, "name": node_tree.name,
                          "bl_idname": node_tree.bl_idname})

    # create folder if more then one node_tree, or if paths are being made relative and there might be dependencies
    if len(to_export) > 1 or context.scene.node_io_dependency_save_type == "2":
        try:
            folder_path = export_path + os_file_sep + folder_name
            mkdir(folder_path)
        except FileExistsError:
            self.report({"ERROR"}, "Directory '{}' Already Exists, Cannot Continue".format(folder_path))
            return
    else:
        folder_path = export_path

    # export materials
    for node_tree in to_export:
        json_root = {}
        names = {}
        data, dependencies = [], []
        m_links, m_nodes = node_tree["links"], node_tree["nodes"]

        # get node data
        collect_nodes(m_nodes, m_links, dependencies, names, "main", data)

        # write data
        # material attribs
        t = datetime.now()
        date_string = "{}/{}/{} at {}:{}:{} in {}".format(t.month, t.day, t.year, t.hour, t.minute,
                                                          t.second, tzname[0])

        node_counter = 0
        for group in names:
            json_root[group] = {'nodes': data[names[group]][0], 'links': data[names[group]][1]}
            node_counter += len(data[names[group]][0])

        # get order of groups
        pre_order = sorted(names.items(), key=operator.itemgetter(1))
        order = [i[0].replace("/", "_") for i in pre_order]
        json_root['__info__'] = {'number_of_nodes': node_counter, 'group_order': order, "render_engine":
                                 context.scene.render.engine, "node_tree_name": node_tree["name"],
                                 "date_created": date_string, "version": version_number, "node_tree_id":
                                     node_tree["bl_idname"]}

        # dependencies
        depend_out = []  # collect all dependencies to place as attribute of root element so they can be imported first

        # absolute filepaths
        if context.scene.node_io_dependency_save_type == "1":
            json_root['__info__']['path_type'] = "absolute"

            # of format [node, node,...] where each node is [depend, depend,...] and depend is [type, name, path]
            for node in dependencies:
                for image in node:
                    depend_out.append([image[0], image[1], bpy.path.abspath(image[2])])
        # relative filepaths
        else:
            json_root['__info__']['path_type'] = "relative"

            for node in dependencies:
                for depend in node:
                    depend_path = bpy.path.abspath(depend[2])
                    depend_out.append([depend[0], depend[1], os_file_sep + depend[1]])
                    copyfile(depend_path, folder_path + os_file_sep + depend[1])

        json_root['__info__']['dependencies'] = depend_out
        save_path = folder_path + os_file_sep + node_tree["name"] + ".bnodes"

        # write file
        try:
            file = open(save_path, 'w')
            json.dump(json_root, file, indent=4 if DEBUG_FILE else 0)
            file.close()
        except (PermissionError, FileNotFoundError):
            self.report({"ERROR"}, "Permission Denied '{}'".format(save_path))
            return

    # zip folder
    if folder_path != export_path and context.scene.node_io_is_compress:  # if folder has been created
        if path.exists(folder_path + ".zip"):  # if zipped file is already there, delete
            remove_file(folder_path + ".zip")

        zf = zipfile.ZipFile(folder_path + ".zip", "w", zipfile.ZIP_DEFLATED)
        for dirname, subdirs, files in walk(folder_path):
            for filename in files:
                zf.write(path.join(dirname, filename), arcname=filename)
        zf.close()

        # delete non-compressed folder
        rmtree(folder_path)


def import_node_tree(self, context):
    import_path = None
    folder_path = None  # use for getting dependencies if needed

    if context.scene.node_io_import_type == "1":  # single file
        import_path = bpy.path.abspath(context.scene.node_io_import_path_file)
        folder_path = path.dirname(import_path)
    else:  # all files in folder
        import_path = bpy.path.abspath(context.scene.node_io_import_path_dir)
        folder_path = import_path

    # check file path
    if not import_path:
        self.report({"ERROR"}, "Empty Import Path")
        return
    elif not path.exists(import_path):
        self.report({"ERROR"}, "Filepath '{}' Does Not Exist".format(import_path))
        return
    elif context.scene.node_io_import_type == "1" and not import_path.endswith(".bnodes"):
        self.report({"ERROR"}, "Filepath Does Not End With .bnodes")
        return

    # collect filepaths
    import_list = []

    if context.scene.node_io_import_type == "2":  # import all files in folder
        files = listdir(import_path)

        for file in files:
            if file.endswith(".bnodes"):
                import_list.append(import_path + os_file_sep + file)
    else:
        import_list.append(import_path)

    # for each .bnodes file import and create material
    for file_path in import_list:
        file = open(file_path, 'r')
        root = json.load(file)
        file.close()

        node_tree, nodes, links = None, None, None

        # determine type
        if root['__info__']['node_tree_id'] == 'ShaderNodeTree':
            node_tree = bpy.data.materials.new(root['__info__']['node_tree_name'])

            # make sure in correct render mode
            if root['__info__']['render_engine'] != context.scene.render.engine:
                self.report({"ERROR"}, "Cannot Continue: Please Switch To '{}' Engine".format(root['__info__']
                                                                                              ['render_engine']))
                return

            context.scene.render.engine = root['__info__']['render_engine']
            node_tree.use_nodes = True
            nodes = node_tree.node_tree.nodes
            links = node_tree.node_tree.links
        elif root['__info__']['node_tree_id'] == "MitsubaShaderNodeTree":
            node_tree = bpy.data.materials.new(root['__info__']['node_tree_name'])
            mitsuba_tree = bpy.data.node_groups.new(name=root['__info__']['node_tree_name'],
                                                    type="MitsubaShaderNodeTree")
            nodes = mitsuba_tree.nodes
            links = mitsuba_tree.links
            node_tree.mitsuba_nodes.nodetree = mitsuba_tree.name

        elif root['__info__']['node_tree_id'] == "an_AnimationNodeTree":
            node_tree = bpy.data.node_groups.new(name=root['__info__']['node_tree_name'],
                                                 type="an_AnimationNodeTree")
            nodes = node_tree.nodes
            links = node_tree.links

        # remove any default nodes
        for i in nodes:
            nodes.remove(i)

        # import dependencies
        dependencies = root['__info__']['dependencies']
        depend_errors = 0

        for depend in dependencies:
            if depend[0] == "image" and depend[1] not in bpy.data.images:
                try:
                    if root['__info__']['path_type'] == "Relative":
                        bpy.data.images.load(folder_path + os_file_sep + depend[1])
                    else:
                        bpy.data.images.load(depend[2])
                except RuntimeError:
                    depend_errors += 1

        if depend_errors:
            self.report({"ERROR"}, str(depend_errors) + " Dependency(ies) Couldn't Be Loaded")

        # add new nodes
        order = root['__info__']['group_order']
        for group_order in order:
            group = root[group_order]

            # set up which node tree to use
            if group_order == "main":
                nt = nodes
            else:
                nt = bpy.data.node_groups.new(group_order, "ShaderNodeTree")

            is_nodes = True  # nodes or links
            parents = []

            for node in group['nodes']:
                parent = {}

                # check if node is custom then make sure it is installed
                if node["bl_idname"] == "GenericNoteNode" and \
                        ("generic_note" not in bpy.context.user_preferences.addons.keys() and
                         "genericnote" not in bpy.context.user_preferences.addons.keys()):

                    self.report({"WARNING"}, "Generic Note Node Add-on Not Installed")
                else:
                    # retrieve node name, create node
                    if group_order != "main":
                        temp = nt.nodes.new(node["bl_idname"])
                    else:
                        temp = nt.new(node["bl_idname"])

                    # node specific is first so that groups are set up first
                    nos = node["node_specific"]
                    if nos:
                        for i in range(0, len(nos), 2):  # step by two because name, value, name, value...
                            att = nos[i]
                            val = nos[i + 1]

                            # group node inputs and outputs
                            if att in ("group_input", "group_output"):
                                for sub in range(0, len(val), 2):
                                    sub_val = [val[sub], val[sub + 1]]
                                    if att == "group_input":
                                        nt.inputs.new(sub_val[0], sub_val[1])
                                    else:
                                        nt.outputs.new(sub_val[0], sub_val[1])
                            elif att == "parent" and val is not None:  # don't set parent in case not created yet
                                parent['parent'] = val
                            elif val is not None:
                                set_attributes(self, temp, val, att)

                    # inputs
                    if node['inputs']:
                        for i in node['inputs']:
                            for val_key in i['values'].keys():
                                if isinstance(i['values'][val_key], str):
                                    exec("temp.inputs[{}].{} = '{}'".format(i['index'], val_key, i['values'][val_key]))
                                else:
                                    exec("temp.inputs[{}].{} = {}".format(i['index'], val_key, i['values'][val_key]))

                    # outputs
                    if node['outputs']:
                        for i in node['outputs']:
                            for val_key in i['values'].keys():
                                if isinstance(i['values'][val_key], str):
                                    exec("temp.outputs[{}].{} = '{}'".format(i['index'], val_key, i['values'][val_key]))
                                else:
                                    exec("temp.outputs[{}].{} = {}".format(i['index'], val_key, i['values'][val_key]))

                    # deal with parent
                    if parent:
                        parent['node'] = temp.name
                        parent['location'] = temp.location
                        parents.append(parent)

            # set parents
            for parent in parents:
                if group_order != "main":
                    nt.nodes[parent['node']].parent = nt.nodes[parent['parent']]
                    nt.nodes[parent['node']].location = parent['location'] + nt.nodes[parent['parent']].location
                else:
                    nt[parent['node']].parent = nt[parent['parent']]
                    nt[parent['node']].location = parent['location'] + nt[parent['parent']].location

            # links
            for link in group['links']:
                if group_order == "main":
                    o = nt[link[0]].outputs[link[1]]
                    i = nt[link[2]].inputs[link[3]]
                    links.new(o, i)
                else:
                    o = nt.nodes[link[0]].outputs[link[1]]
                    i = nt.nodes[link[2]].inputs[link[3]]
                    nt.links.new(o, i)

                is_nodes = not is_nodes

        if root['__info__']['node_tree_id'] not in ("MitsubaShaderNodeTree", "an_AnimationNodeTree"):
            # get rid of extra groups
            for i in bpy.data.node_groups:
                if i.users == 0:
                    bpy.data.node_groups.remove(i)

        # add material to object
        if context.object is not None and context.scene.node_io_is_auto_add and root['__info__']['node_tree_id'] in \
                ('ShaderNodeTree', 'MitsubaShaderNodeTree'):
            context.object.data.materials.append(node_tree)


def s_to_t(s):
    tu = s.split(", ")
    tu[0] = tu[0].replace("(", "")
    tu[len(tu) - 1] = tu[len(tu) - 1].replace(")", "")

    return [float(i) for i in tu]


def set_attributes(self, temp, val, att):
    # determine attribute type, exec() can be used if value gets directly set to attribute
    if att == "image" and val in bpy.data.images:
        temp.image = bpy.data.images[val]
    elif att == 'an_list_size':  # add correct number of inputs for animation node list
        temp.removeElementInputs()
        for i in range(val):
            temp.newInputSocket()
    elif att == "object" and val in bpy.data.objects:
        temp.object = bpy.data.objects[val]
    elif att == "particle_system" and val[0] in bpy.data.objects \
            and val[1] in bpy.data.objects[val[0]].particle_systems:
        temp.particle_system = bpy.data.objects[val[0]].particle_systems[val[1]]
    elif att == "color_ramp.elements":
        e = temp.color_ramp.elements
        if len(val) >= 2:
            e[0].position = val[0][0]
            e[0].color = val[0][1]
            e[1].position = val[1][0]
            e[1].color = val[1][1]
            del val[0:2]
        for el in val:
            e_temp = e.new(el[0])
            e_temp.color = el[1]
    elif att == "node_tree.name" and val in bpy.data.node_groups:
        temp.node_tree = bpy.data.node_groups[val]
    elif att == "material" and val in bpy.data.materials:
        temp.material = bpy.data.materials[val]
    elif att == "mapping":
        if temp.bl_idname == "an_InterpolationFromCurveMappingNode":  # contains ShaderNodeRGBCurve, which has curve
            node = temp.curveNode
        else:
            node = temp
        # set curves
        node.mapping.black_level = val[0]
        node.mapping.white_level = val[1]
        node.mapping.clip_max_x = float(val[2])
        node.mapping.clip_max_y = float(val[3])
        node.mapping.clip_min_x = float(val[4])
        node.mapping.clip_min_y = float(val[5])
        node.mapping.use_clip = True if val[6] == "True" else False

        for i in range(7):
            del val[0]

        # go through each curve
        counter = 0
        for i in val:
            # set first two points
            curves = node.mapping.curves
            curves[counter].extend = i[0]
            del i[0]
            curves[counter].points[0].location = i[0][0]
            curves[counter].points[0].handle_type = i[0][1]
            curves[counter].points[1].location = i[1][0]
            curves[counter].points[1].handle_type = i[1][1]
            del i[0:2]
            for i2 in i:
                temp_point = node.mapping.curves[counter].points.new(i2[0][0], i2[0][1])
                temp_point.handle_type = i2[1]
            counter += 1
    else:
        try:
            if isinstance(val, str):
                exec("temp.{} = '{}'".format(att, val))
            else:
                exec("temp.{} = {}".format(att, val))
        except AttributeError:
            self.report({"WARNING"}, "NodeIO: Attribute Error, Name={}, ID={}, Attribute={}, Value={}".
                        format(temp.name, temp.bl_idname, att, val))

# PROPERTIES
bpy.types.Scene.node_io_import_export = EnumProperty(name="Import/Export", items=(("1", "Import", ""),
                                                                                  ("2", "Export", "")))
bpy.types.Scene.node_io_export_path = StringProperty(name="Export Path", subtype="DIR_PATH")
bpy.types.Scene.node_io_import_path_file = StringProperty(name="Import Path", subtype="FILE_PATH")
bpy.types.Scene.node_io_import_path_dir = StringProperty(name="Import Path", subtype="DIR_PATH")
bpy.types.Scene.node_io_dependency_save_type = EnumProperty(name="Image Path", items=(("1", "Absolute Paths", ""),
                                                                                      ("2", "Make Paths Relative", "")),
                                                            default="1")
bpy.types.Scene.node_io_is_auto_add = BoolProperty(name="Add Node Tree To Object?", default=True)
bpy.types.Scene.node_io_import_type = EnumProperty(name="Import Type", items=(("1", "Single", ""),
                                                                              ("2", "Multiple", "")))
bpy.types.Scene.node_io_is_compress = BoolProperty(name="Compress Folder?")


class NodeIOPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_node_io_panel"
    bl_label = "NodeIO Panel"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    
    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "node_io_import_export")
        layout.separator()
        
        if context.scene.node_io_import_export == "2":
            layout.prop(context.scene, "node_io_dependency_save_type")
            layout.prop(context.scene, "node_io_is_compress", icon="FILTER")
            layout.separator()
            layout.prop(context.scene, "node_io_export_path")
            layout.separator()
            layout.operator("export.node_io_export", icon="ZOOMOUT")
                  
        else:
            layout.prop(context.scene, "node_io_import_type")
            layout.prop(context.scene, "node_io_is_auto_add", icon="NODETREE")
            layout.separator()

            if context.scene.node_io_import_type == "1":
                layout.prop(context.scene, "node_io_import_path_file")
            else:
                layout.prop(context.scene, "node_io_import_path_dir")
            layout.separator()

            layout.operator("import.node_io_import", icon="ZOOMIN")


class NodeIOExport(bpy.types.Operator):
    bl_idname = "export.node_io_export"
    bl_label = "Export Node Tree"
    
    def execute(self, context):
        export_node_tree(self, context)
        return {"FINISHED"}


class NodeIOImport(bpy.types.Operator):
    bl_idname = "import.node_io_import"
    bl_label = "Import Node Tree"
    
    def execute(self, context):
        import_node_tree(self, context)
        return {"FINISHED"}             


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
