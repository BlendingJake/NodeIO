bl_info = {
    "name": "Material IO",
    "author": "Jacob Morris",
    "version": (1, 4),
    "blender": (2, 78, 0),
    "location": "Properties > Materials",
    "description": "Allows The Exporting And Importing Of Materials Via .bmat Files",
    "category": "Import-Export"
    }

import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty
from datetime import datetime
from time import tzname
import xml.etree.cElementTree as ET
import ast
import operator
from os import path, makedirs, listdir, walk, remove as remove_file, sep as os_file_sep
from shutil import copyfile, rmtree
from xml.dom.minidom import parse as pretty_parse
import zipfile
import string


def make_tuple(data):
    out = [round(i, 4) for i in data]
    return tuple(out)


def serialize(name):  # serialize names
    f = ""
    for i in name:
        if i not in string.ascii_letters and i not in string.digits and i != "_":
            f += "_"
        else:
            f += i   
    return f


def export_node_type(n):
    t = n.type
    is_group = False
    images = []

    # basic info
    out = {"name": serialize(n.name), "bl_idname": n.bl_idname, "label": serialize(n.label),
           "location": make_tuple(n.location), "hide": str(n.hide), "height": str(n.height), "width": str(n.width),
           "mute": str(n.mute), "color": make_tuple(n.color), "use_custom_color": str(n.use_custom_color)}

    if n.parent is None:
        out["parent"] = n.parent
    else:
        out["parent"] = serialize(n.parent.name)

    ns = []  # node specific information
    i = []  # inputs
    o = []  # outputs
    
    # inputs
    for j in range(len(n.inputs)):                
        if t not in ("GROUP_INPUT", "GROUP_OUTPUT"):
            data = n.inputs[j]
            if data.type in ("RGBA", "RGB", "VECTOR"):
                i.append(j)
                i.append(make_tuple(data.default_value))
            elif data.type == "VALUE":
                i.append(j)
                i.append(data.default_value)
            elif t == "GROUP" and data.type == "SHADER":
                i.append(j)
                i.append("SHADER")         
    
    # input nodes
    if t == "TEX_COORD":
        ns = ["from_dupli", n.from_dupli]
    elif t == "ATTRIBUTE":
        ns = ["attribute_name", n.attribute_name]
    elif t == "TANGENT":
        ns = ["direction_type", n.direction_type, "axis", n.axis]
    elif t == "WIREFRAME":
        ns = ["use_pixel_size", n.use_pixel_size]
    elif t == "UVMAP":
        ns = ["uv_map", n.uv_map, "from_dupli", n.from_dupli]
    elif t == "LAMP":
        ns = ["lamp_object", n.lamp_object]
    elif t == "MATERIAL":
        ns = ["use_diffuse", n.use_diffuse, "use_specular", n.use_specular, "invert_normal", n.invert_normal,
              "material", n.material.name]
    # shader nodes
    elif t == "BSDF_GLOSSY":
        ns = ["distribution", n.distribution]
    elif t in ("BSDF_REFRACTION", "BSDF_GLASS", "BSDF_TOON", "VOLUME_SCATTER"):
        if t in ("BSDF_REFRACTION", "BSDF_GLASS"):
            ns = ["distribution", n.distribution]
        elif t == "BSDF_TOON":
            ns = ["component", n.component]
    elif t == "BSDF_ANISOTROPIC":
        ns = ["distribution", n.distribution]
    elif t == "SUBSURFACE_SCATTERING":
        ns = ["falloff", n.falloff]    
    elif t == "BSDF_HAIR":
        ns = ["component", n.component]
    # texture nodes
    elif t == "TEX_IMAGE":
        ns = ["color_space", n.color_space, "projection", n.projection, "interpolation", n.interpolation]
        if n.image is not None:
            ns += ["image", n.image.name]
            images.append([n.image.name, n.image.filepath])
    elif t == "TEX_ENVIROMENT":
        ns = ["image", n.image.name, "color_space", n.color_space, "projection", n.projection]
        if n.image is not None:
            ns += ["image", n.image.name]
            images.append([n.image.name, n.image.filepath])
    elif t == "TEX_SKY":
        ns = ["sky_type", n.sky_type, "sun_direction", make_tuple(n.sun_direction), "turbidity", n.turbidity,
              "ground_albedo", n.ground_albedo]
    elif t == "TEX_WAVE":
        ns = ["wave_type", n.wave_type]
    elif t == "TEX_VORONOI":
        ns = ["coloring", n.coloring]
    elif t == "TEX_MUSGRAVE":
        ns = ["musgrave_type", n.musgrave_type]
    elif t == "TEX_GRADIENT":
        ns = ["gradient_type", n.gradient_type]
    elif t == "TEX_MAGIC":
        ns = ["turbulence_depth", n.turbulence_depth]
    elif t == "TEX_BRICK":
        ns = ["offset", n.offset, "squash", n.squash, "offset_frequency", n.offset_frequency, "squash_frequency",
              n.squash_frequency]
    elif t == "TEX_POINTDENSITY":
        ns = ["point_source", n.point_source, "object", n.object.name, "particle_system",
              [n.object.name, n.particle_system.name], "space", n.space, "radius", n.radius, "interpolation",
              n.interpolation, "resolution", n.resolution, "particle_color_source", n.particle_color_source]
    # Color nodes
    elif t == "MIX_RGB":
        ns = ["blend_type", n.blend_type, "use_clamp", n.use_clamp]
    elif t in ("CURVE_RGB", "CURVE_VEC"):
        # get curves
        curves = [make_tuple(n.mapping.black_level), make_tuple(n.mapping.white_level), str(n.mapping.clip_max_x),
                  str(n.mapping.clip_max_y), str(n.mapping.clip_min_x), str(n.mapping.clip_min_y),
                  str(n.mapping.use_clip)]

        for curve in n.mapping.curves:
            points = [curve.extend]
            for point in curve.points:
                points.append([make_tuple(point.location), point.handle_type])
            curves.append(points)
        ns = ["mapping", curves]
    # Vector nodes
    elif t == "MAPPING":
        ns = ["vector_type", n.vector_type, "translation", make_tuple(n.translation), "rotation", make_tuple(n.rotation),
              "scale", make_tuple(n.scale), "use_min", n.use_min, "use_max", n.use_max, "min", make_tuple(n.min),
              "max", make_tuple(n.max)]
    elif t == "BUMP":
        ns = ["invert", n.invert]
    elif t == "NORMAL_MAP":
        ns = ["space", n.space, "uv_map", n.uv_map]
    elif t == "NORMAL":
        o = [0, make_tuple(n.outputs[0].default_value)]
    elif t == "VECT_TRANSFORM":
        ns = ["vector_type", n.vector_type, "convert_from", n.convert_from, "convert_to", n.convert_to]
    # Converter nodes
    elif t == "MATH":
        ns = ["operation", n.operation, "use_clamp", n.use_clamp]
    elif t == "VALTORGB":
        els = []
        for j in n.color_ramp.elements:
            cur_el = [j.position, make_tuple(j.color)]            
            els.append(cur_el)       
        ns = ["color_ramp.color_mode", n.color_ramp.color_mode, "color_ramp.interpolation", n.color_ramp.interpolation, "color_ramp.elements", els]
    elif t == "VECT_MATH":
        ns = ["operation", n.operation]      
    # Script node
    elif t == "SCRIPT":
        ns = ["mode", n.mode, "script", n.script]
    # Group nodes
    elif t == "GROUP":
        is_group = True              
        ns = ["node_tree.name", serialize(n.node_tree.name)]
    elif t == "GROUP_INPUT":
        temp = []
        for i2 in n.outputs:
            if i2.type != "CUSTOM":
                temp.append(i2.bl_idname)
                temp.append(serialize(i2.name))
            ns = ["group_input", temp]
    elif t == "GROUP_OUTPUT":
        temp = []
        for i2 in n.inputs:
            if i2.type != "CUSTOM":
                temp.append(i2.bl_idname)
                temp.append(serialize(i2.name))
        ns = ["group_output", temp]
        
    # Add-on Specific
    elif t == "CUSTOM":
        node_id = n.bl_idname

        # Generic Note Node Add-on
        if node_id == "GenericNoteNode":
            if n.text == "" and n.text_file != "":
                text = ""
                t_file = bpy.data.texts.get(n.text_file)
                for line in t_file.lines:
                    text += line.body + "\n"
            else:
                text = n.text
                
            ns = ["text", text]
        
        # Mitsuba nodes
        elif node_id == "MtsNodeInput_spectrum":
            ns = ["samples", n.samples, "wavelength", n.wavelength, "value", n.value]
        elif node_id == "MtsNodeInput_spdfile":
            ns = ["filename", n.filename]
        elif node_id == "MtsNodeInput_blackbody":
            ns = ["temperature", n.temperature, "scale", n.scale]
        elif node_id == "MtsNodeInput_uvmapping":
            ns = ["uscale", n.uscale, "vscale", n.vscale, "uoffset", n.uoffset, "voffset", n.voffset]
        elif node_id == "MtsNodeInput_rgb":
            ns = ["color_mode", n.color_mode, "color", make_tuple(n.color), "gain_r", n.gain_r, "gain_g", n.gain_g,
                  "gain_b", n.gain_b]
        # BSDF
        elif node_id == "MtsNodeBsdf_diffuse":
            ns = ["useFastApprox", n.useFastApprox]
        elif node_id == "MtsNodeBsdf_dielectric":
            ns = ["thin", n.thin, "intIOR", n.intIOR, "extIOR", n.extIOR, "distribution", n.distribution,
                  "anisotropic", n.anisotropic]
        elif node_id == "MtsNodeBsdf_conductor":
            ns = ["material", n.material, "extEta", n.extEta, "distribution", n.distribution, "anisotropic",
                  n.anisotropic]
        elif node_id == "MtsNodeBsdf_plastic":
            ns = ["intIOR", n.intIOR, "extIOR", n.extIOR, "nonlinear", n.nonlinear, "distribution", n.distribution]
        elif node_id == "MtsNodeBsdf_coating":
            ns = ["intIOR", n.intIOR, "extIOR", n.extIOR, "thickness", n.thickness, "distribution", n.distribution]
        elif node_id == "MtsNodeBsdf_bumpmap":
            ns = ["scale", n.scale]
        elif node_id == "MtsNodeBsdf_ward":
            ns = ["variant", n.variant, "anisotropic", n.anisotropic]
        elif node_id == "MtsNodeBsdf_hk":
            ns = ["useAlbSigmaT", n.useAlbSigmaT, "thickness", n.thickness]
        # Texture
        elif node_id == "MtsNodeTexture_bitmap":
            ns = ["filename", n.filename, "wrapModeU", n.wrapModeU, "wrapModeV", n.wrapModeV, "gammaType", n.gammaType,
                  "filterType", n.filterType, "cache", n.cache, "maxAnisotropy", n.maxAnisotropy]
            images.append([n.filename, n.filename])
        elif node_id == "MtsNodeTexture_gridtexture":
            ns = ["lineWidth", n.lineWidth]
        elif node_id == "MtsNodeTexture_scale":
            ns = ["scale", n.scale]
        elif node_id == "MtsNodeTexture_wireframe":
            ns = ["lineWidth", n.lineWidth, "stepWidth", n.stepWidth]
        elif node_id == "MtsNodeTexture_curvature":
            ns = ["curvature", n.curvature, "scale", n.scale]
        # Subsurface
        elif node_id == "MtsNodeSubsurface_dipole":
            ns = ["useAlbSigmaT", n.useAlbSigmaT, "scale", n.scale, "intIOR", n.intIOR, "extIOR", n.extIOR]
        elif node_id == "MtsNodeSubsurface_singlescatter":
            ns = ["fastSingleScatter", n.fastSingleScatter, "fssSamples", n.fssSamples, "singleScatterDepth",
                  n.singleScatterDepth, "useAlbSigmaT", n.useAlbSigmaT]
        # Emitter
        elif node_id in ("MtsNodeEmitter_area", "MtsNodeEmitter_point", "MtsNodeEmitter_spot", "MtsNodeEmitter_directional",
                    "MtsNodeEmitter_collimated"):
            if node_id == "MtsNodeEmitter_point":
                ns = ["size", n.size]
            elif node_id == "MtsNodeEmitter_spot":
                ns = ["cutoffAngle", n.cutoffAngle, "spotBlend", n.spotBlend, "showCone", n.showCone]
                
            if ns == "":
                ns = ["samplingWeight", n.samplingWeight, "scale", n.scale]
            else:
                ns = ["samplingWeight", n.samplingWeight, "scale", n.scale]
        
    # layout
    if len(ns) == 0:
        ns = ""
    if len(i) == 0:
        i = ""
    if len(o) == 0:
        o = ""
                        
    out["node_specific"] = ns
    out["inputs"] = i
    out["outputs"] = o

    return out, is_group, images


# recursive method that collects all nodes and if group node goes and collects its nodes
# data is added to data in [[nodes, links], [nodes, links]] group by group
def collect_nodes(nodes, links, images, names, name, data):
    m_n = []
    m_l = []
    
    for n in nodes:  # nodes
        out, is_group, im = export_node_type(n)
        m_n.append(out)
        images.append(im)
        
        if is_group:
            collect_nodes(n.node_tree.nodes, n.node_tree.links, images, names, n.node_tree.name, data)    
        
    for l in links:  # links
        out = link_info(l)
        m_l.append(out)
        
    data.append([m_n, m_l])   
    names[name] = len(data) - 1 


def link_info(link):
    out = [serialize(link.from_node.name)]

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
    out.append(serialize(link.to_node.name))
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


def export_material(self, context):
    mat_list = []
    et = context.scene.export_materials_type
    folder_path = ""
    folder_name = ""

    # determine what all is being exported
    if et == "1" and context.material is not None:
        mat_list.append(context.material.name)
    elif et == "2":
        for i in context.object.data.materials:
            mat_list.append(i.name)
    elif et == "3":
        for i in bpy.data.materials:
            mat_list.append(i.name)

    # export materials
    for mat_name in mat_list:
        # check render engine to see where nodes are located at
        if context.scene.render.engine in ("CYCLES", "BLENDER_RENDER"):
            mat = bpy.data.materials[mat_name]
        # mitsuba nodes are in a node group that is linked up to the material
        elif context.scene.render.engine == "MITSUBA_RENDER":
            if bpy.data.materials[mat_name].mitsuba_nodes.nodetree in bpy.data.node_groups:
                mat = bpy.data.node_groups[bpy.data.materials[mat_name].mitsuba_nodes.nodetree]
            else:
                mat = None
            
        epath = context.scene.save_path_export
        
        if mat is not None:
            if epath != "":
                # try open file
                error = True

                if "//" in epath:
                    epath = bpy.path.abspath(epath)
                if path.exists(epath):
                    error = False

                if not error:
                    root = ET.Element("material")
                    names = {}
                    data = []
                    images = []
                    
                    node_group_name = ""
                    
                    # main node and links sources depending on what render engine
                    if context.scene.render.engine in ("CYCLES", "BLENDER_RENDER"):
                        m_links = mat.node_tree.links
                        m_nodes = mat.node_tree.nodes
                    # mitsuba nodes are in a node group that is linked up to the material
                    elif context.scene.render.engine == "MITSUBA_RENDER":
                        m_links = mat.links
                        m_nodes = mat.nodes
                        node_group_name = bpy.data.materials[mat_name].mitsuba_nodes.nodetree  
                        
                    # get node data
                    collect_nodes(m_nodes, m_links, images, names, "main", data)                                                                                       
                                                                                                                                                           
                    # write data
                    # material attribs
                    t = datetime.now()
                    date_string = "{}/{}/{} at {}:{}:{} in {}".format(t.month, t.day, t.year, t.hour, t.minute,
                                                                      t.second, tzname[0])

                    root.attrib = {"Render_Engine": context.scene.render.engine, "Material_Name": serialize(mat.name),
                                   "Node_Group_Name": serialize(node_group_name), "Date_Created": date_string,
                                   "Number_Of_Nodes": ""}

                    n = 0
                    num_nodes = 0
                    for group in names:
                        sub_e = ET.SubElement(root, group.replace("/", "_"))
                        d = data[names[group]]
                        sub_e_nodes = ET.SubElement(sub_e, group.replace("/", "_") + "_nodes")
                        for i in d[0]:  # nodes
                            ET.SubElement(sub_e_nodes, "node" + str(n), {"name": i["name"], "bl_idname": i["bl_idname"],
                                                                         "label": i["label"], "color": i["color"],
                                                                         "parent": str(i["parent"]),
                                                                         "location": i["location"],
                                                                         "height": i["height"], "width": i["width"],
                                                                         "mute": i["mute"], "hide": i["hide"],
                                                                         "inputs": i["inputs"], "outputs": i["outputs"],
                                                                         "node_specific": i["node_specific"],
                                                                         "use_custom_color": i["use_custom_color"]})
                            num_nodes += 1

                        sub_e_links = ET.SubElement(sub_e, group.replace("/", "_") + "_links")
                        for i in d[1]:  # links
                            ET.SubElement(sub_e_links, "link" + str(n), {"link_info": i})
                            n += 1

                    root.attrib["Number_Of_Nodes"] = str(num_nodes)
                    # get order of groups
                    pre_order = sorted(names.items(), key=operator.itemgetter(1))
                    order = [i[0].replace("/", "_") for i in pre_order]
                    root.attrib["Group_Order"] = str(order)

                    # images
                    img_out = []
                    save_path = epath + serialize(mat.name) + ".bmat"
                    # create folder if needed
                    if (et == "2" and len(context.object.data.materials) >= 2) or \
                            (et == "3" and len(bpy.data.materials) >= 2):

                        if not path.exists(epath + serialize(mat.name)) and folder_path == "":
                            try:
                                makedirs(epath + serialize(mat.name))
                                folder_path = epath + serialize(mat.name)
                                folder_name = serialize(mat.name)
                            except PermissionError:
                                raise PermissionError("Cannot Write At '{}'".format(epath+serialize(mat.name)))
                        elif folder_path == "":
                            folder_path = epath + serialize(mat.name)

                    # set save path based on folder path
                    if folder_path != "":
                        save_path = path.join(folder_path, serialize(mat.name) + ".bmat")
                    # image file paths
                    if context.scene.image_save_type == "1":  # absolute filepaths
                        root.attrib["Path_Type"] = "Absolute"                                       
                        for i in images:
                            for i2 in i:
                                img_out.append([i2[0], bpy.path.abspath(i2[1])])
                    else:  # relative filepaths
                        error = False
                        for i in images:
                            if not i:
                                error = True
                        if error:
                            save_path = path.join(epath + serialize(mat.name), serialize(mat.name) + ".bmat")
                            image_path = epath + serialize(mat.name)
                            if not path.exists(epath + serialize(mat.name)) and folder_path == "":
                                try:
                                    makedirs(epath + serialize(mat.name))
                                    folder_path = epath + serialize(mat.name)
                                    folder_name = serialize(mat.name)
                                except PermissionError:
                                    error = False
                            elif folder_path != "":
                                save_path = path.join(folder_path, serialize(mat.name) + ".bmat")
                                image_path = folder_path
                            # make sure folder_path is correct
                            if path.exists(epath + serialize(mat.name)) and folder_path == "":
                                folder_path = epath + serialize(mat.name)
                        root.attrib["Path_Type"] = "Relative"
                        if error:
                            for i in images:
                                for i2 in i:
                                    i3 = bpy.path.abspath(i2[1])
                                    i2_l = i3.split(os_file_sep)
                                    img_out.append([i2[0], os_file_sep + i2_l[len(i2_l) - 1]])
                                    if path.exists(image_path):
                                        copyfile(i3, image_path + os_file_sep + i2_l[len(i2_l) - 1])
                
                    root.attrib["Images"] = str(img_out)                                                
                    tree = ET.ElementTree(root)
                    error2 = True
                    try:
                        tree.write(save_path)
                        error2 = False                    
                    except (PermissionError, FileNotFoundError):
                        self.report({"ERROR"}, "Permission Denied '{}'".format(save_path))

                    # if no error make text pretty
                    if not error2:
                        pretty_file = pretty_parse(save_path)
                        pretty_text = pretty_file.toprettyxml()
                        file = open(save_path, "w+")
                        file.write(pretty_text)
                        file.close()
                # if error
                elif error:
                    self.report({"ERROR"}, "Export Path Is Invalid") 

    # zip folder
    if folder_path != "" and context.scene.compress_folder:
        if path.exists(path.join(epath, folder_name + ".zip")):  # if file is already there, delete
            remove_file(path.join(epath, folder_name + ".zip"))

        zf = zipfile.ZipFile(path.join(epath, folder_name + ".zip"), "w", zipfile.ZIP_DEFLATED)
        for dirname, subdirs, files in walk(folder_path):
            for filename in files:
                zf.write(path.join(dirname, filename), arcname=filename)
        zf.close()

        # delete non-compressed folder
        rmtree(folder_path)


def import_material(self, context):
    temp_epath = context.scene.save_path_import

    if temp_epath != "" and path.exists(bpy.path.abspath(temp_epath)) and temp_epath.endswith(".bmat"):
         #if multiple files then import them all
        import_list = []

        if context.scene.import_materials_type == "2":  # import all files in folder
            folder_path = path.dirname(bpy.path.abspath(temp_epath))
            files = listdir(folder_path)            
            
            for i in files:
                if i.endswith(".bmat"):
                    import_list.append(folder_path + os_file_sep + i)
        else:
            if os_file_sep in temp_epath:
                temp_epath = bpy.path.abspath(temp_epath)       
            import_list.append(temp_epath)
            
        # for each .bmat file import and create material
        for file_name in import_list:
            epath = file_name
            tree = ET.parse(epath)
            root = tree.getroot()
            mat = bpy.data.materials.new(root.attrib["Material_Name"])
            skip = False
            
            # check and see render engine data
            if root.attrib["Render_Engine"] in ("BLENDER_RENDER", "CYCLES"):
                mat.use_nodes = True
                nodes = mat.node_tree.nodes
                m_links = mat.node_tree.links
                context.scene.render.engine = root.attrib["Render_Engine"]
            elif root.attrib["Render_Engine"] == "MITSUBA_RENDER" and context.scene.render.engine == "MITSUBA_RENDER":
                # set up node group
                node_group = bpy.data.node_groups.new(name=root.attrib["Node_Group_Name"], type="MitsubaShaderNodeTree")
                nodes = node_group.nodes
                m_links = node_group.links 
                mat.mitsuba_nodes.nodetree = node_group.name              
            else:
                skip = True                            
                
            # import images
            images = ast.literal_eval(root.attrib["Images"])
            errors = 0
            
            # skip if issue with render engine
            if not skip:
                
                # get rid of current nodes like BSDF Diffuse and Output node
                for i in nodes:
                    nodes.remove(i)
                
                # don't load image if Render_Engine is MITSUBA_RENDER
                if root.attrib["Render_Engine"] != "MITSUBA_RENDER":
                    for i in images:
                        if i[0] not in bpy.data.images:
                            if root.attrib["Path_Type"] == "Relative":
                                root_path = path.dirname(bpy.path.abspath(context.scene.save_path_import)) + os_file_sep
                                try:                
                                    bpy.data.images.load(root_path + i[0])
                                except RuntimeError:
                                    errors += 1
                            else:
                                try:
                                    bpy.data.images.load(i[1])
                                except RuntimeError:
                                    errors += 1
                    if errors != 0:
                        self.report({"ERROR"}, str(errors) + " Picture(s) Couldn't Be Loaded")
                    
                # add new nodes
                order = ast.literal_eval(root.attrib["Group_Order"])
                for group_order in order:
                    group = root.findall(group_order)[0]
                    counter = 0

                    # set up which node tree to use
                    if group.tag == "main":
                        nt = nodes
                    else:            
                        nt = bpy.data.node_groups.new(group.tag, "ShaderNodeTree")

                    for data in group:
                        if counter == 0:  # nodes
                            parents = []
                            for node in data:
                                node_created = True                            
                                # check if node is custom and if it is make sure addon is installed
                                if node.attrib["bl_idname"] == "GenericNoteNode" and \
                                        ("generic_note" not in bpy.context.user_preferences.addons.keys() and
                                                 "genericnote" not in bpy.context.user_preferences.addons.keys()):

                                    node_created = False
                                    self.report({"WARNING"}, "Generic Note Node Addon Not Installed")
                                    
                                if node_created:
                                    # parse name
                                    # create node in group or just create it
                                    if group.tag != "main":    
                                        temp = nt.nodes.new(node.attrib["bl_idname"])
                                    else:
                                        temp = nt.new(node.attrib["bl_idname"])
                                        
                                    # adjust basic node attributes
                                    temp.location = s_to_t(node.attrib["location"])
                                    temp.name = node.attrib["name"]
                                    temp.label = node.attrib["label"]
                                    temp.mute = ast.literal_eval(node.attrib["mute"])
                                    temp.height = float(node.attrib["height"])
                                    temp.width = float(node.attrib["width"])
                                    
                                    # see if custom color is in file, should be if newer version
                                    try:
                                        if node.attrib["use_custom_color"] == "True":
                                            temp.use_custom_color = True                                                                  
                                        temp.color = s_to_t(node.attrib["color"])
                                    except:
                                        print("This File Is Older And Doesn't Contain Custom Color")
                                                                        
                                    # parent
                                    if node.attrib["parent"] != "None":
                                        parents.append([node.attrib["name"], node.attrib["parent"],
                                                        s_to_t(node.attrib["location"])])
                                    
                                    # hide if needed
                                    if node.attrib["hide"] == "True":
                                        temp.hide = True
                                    
                                    # node specific is first so that groups are set up first
                                    nos = node.attrib["node_specific"]
                                    if nos != "":
                                        nod = ast.literal_eval(nos)
                                        for i in range(0, len(nod), 2):  # step by two because name, value...
                                            att = nod[i]
                                            val = nod[i + 1]
                                           
                                            # check and see if this is filename, if so change value
                                            if att == "filename":
                                                image_path_list = val.split(os_file_sep)
                                                mat_path_list = file_name.split(os_file_sep)
                                                del mat_path_list[len(mat_path_list) - 1]
                                                
                                                image_path_string = ""
                                                for i2 in mat_path_list:
                                                    if i2 != "":
                                                        image_path_string += i2 + os_file_sep
                                                        
                                                image_path_string += image_path_list[len(image_path_list) - 1]
                                                val = image_path_string
                                                
                                            set_attributes(temp, val, att)
                                            if att in ("group_input", "group_output"):
                                                for sub in range(0, len(val), 2):
                                                    sub_val = [val[sub], val[sub + 1]]
                                                    if att == "group_input":
                                                        nt.inputs.new(sub_val[0], sub_val[1])
                                                    else:
                                                        nt.outputs.new(sub_val[0], sub_val[1])                                
                                    # inputs
                                    ins = node.attrib["inputs"]              
                                    if ins != "":
                                        inp = ast.literal_eval(ins)
                                        for i in range(0, len(inp), 2):
                                            if inp[i + 1] != "SHADER":
                                                temp.inputs[inp[i]].default_value = inp[i + 1]
                                    # outputs
                                    ous = node.attrib["outputs"]
                                    if ous != "":
                                        out = ast.literal_eval(ous)
                                        for i in range(0, len(out), 2):
                                            temp.outputs[out[i]].default_value = out[i + 1]                    
                            # set parents
                            for parent in parents:
                                if group.tag != "main":
                                    nt.nodes[parent[0]].parent = nt.nodes[parent[1]]
                                    nt.nodes[parent[0]].location = parent[2]
                                else:
                                    nt[parent[0]].parent = nt[parent[1]]                                
                                    nt[parent[0]].location = parent[2]
                        
                        # create links
                        elif counter == 1:
                            for link in data:
                                ld = ast.literal_eval(link.attrib["link_info"])                    
                                if group.tag == "main":
                                    o = nt[ld[0]].outputs[ld[1]]
                                    i = nt[ld[2]].inputs[ld[3]]
                                    m_links.new(o, i)                        
                                else:
                                    o = nt.nodes[ld[0]].outputs[ld[1]]
                                    i = nt.nodes[ld[2]].inputs[ld[3]]
                                    nt.links.new(o, i)
                                        
                        counter += 1
                                    
                if root.attrib["Render_Engine"] != "MITSUBA_RENDER":                                                    
                    # get rid of extra groups
                    for i in bpy.data.node_groups:
                        if i.users == 0:
                            bpy.data.node_groups.remove(i)
                        
                # add material to object
                if context.object is not None and context.scene.add_material_auto:
                    context.object.data.materials.append(mat)
            
            # if there is a skip because of render engine
            else:
                self.report({"ERROR"}, "Please Switch To The {} Render Engine".format(root.attrib["Render_Engine"]))
    else:
        if temp_epath == "" or not path.exists(bpy.path.abspath(temp_epath)):
            self.report({"ERROR"}, "File Could Not Be Imported")
        else:
            self.report({"ERROR"}, "This File Is Not A .bmat File")                         


def s_to_t(s):
    tu = s.split(", ")
    tu[0] = tu[0].replace("(", "")
    tu[len(tu) - 1] = tu[len(tu) - 1].replace(")", "")

    return [float(i) for i in tu]


def set_attributes(temp, val, att):
    # determine attribute type, exec() can be used if value gets directly set to attribute
    if att == "image":
        try:
            temp.image = bpy.data.images[val]
        except KeyError:
            pass
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
    elif att == "node_tree.name":
        temp.node_tree = bpy.data.node_groups[val]
    elif att == "material":
        try:
            temp.material = bpy.data.materials[val]
        except KeyError:
            pass
    elif att == "mapping":
        # set curves
        temp.mapping.black_level = val[0]
        temp.mapping.white_level = val[1]
        temp.mapping.clip_max_x = float(val[2])
        temp.mapping.clip_max_y = float(val[3])
        temp.mapping.clip_min_x = float(val[4])
        temp.mapping.clip_min_y = float(val[5])
        temp.mapping_use_clip = True if val[6] == "True" else False

        for i in range(7):
            del val[0]

        # go through each curve
        counter = 0
        for i in val:            
            # i == [[location, handle_type], [location, handle_type]] so forth for however many points on curve
            # set first two points
            curves = temp.mapping.curves
            curves[counter].extend = i[0]
            del i[0]
            curves[counter].points[0].location = i[0][0]
            curves[counter].points[0].handle_type = i[0][1]
            curves[counter].points[1].location = i[1][0]
            curves[counter].points[1].handle_type = i[1][1]
            del i[0:2]
            for i2 in i:
                temp_point = temp.mapping.curves[counter].points.new(i2[0][0], i2[0][1])
                temp_point.handle_type = i2[1]
            counter += 1
    elif val != "":
        if isinstance(val, str):
            exec("temp.{} = '{}'".format(att, val))
        else:
            exec("temp.{} = {}".format(att, val))

# PROPERTIES
bpy.types.Scene.import_export_mat = EnumProperty(name="Import/Export", items=(("1", "Import", ""), ("2", "Export", "")))
bpy.types.Scene.save_path_export = StringProperty(name="Export Path", subtype="DIR_PATH")
bpy.types.Scene.save_path_import = StringProperty(name="Import Path", subtype="FILE_PATH")
bpy.types.Scene.image_save_type = EnumProperty(name="Image Path", items=(("1", "Absolute Paths", ""),
                                                                         ("2", "Make Paths Relative", "")))
bpy.types.Scene.add_material_auto = BoolProperty(name="Add Material To Object?", default=True)
bpy.types.Scene.export_materials_type = EnumProperty(name="Export Type", items=(("1", "Selected", ""),
                                                                                ("2", "Current Object", ""),
                                                                                ("3", "All Materials", "")))
bpy.types.Scene.import_materials_type = EnumProperty(name="Import Type", items=(("1", "Single", ""),
                                                                                ("2", "Multiple", "")))
bpy.types.Scene.compress_folder = BoolProperty(name="Compress Folder?")


class MaterialIOPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_material_io_panel"
    bl_label = "Material IO Panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_category = "material"
    bl_context = "material"       
    
    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "import_export_mat")
        layout.separator()
        
        if context.scene.import_export_mat == "2":
            layout.prop(context.scene, "save_path_export")
            layout.prop(context.scene, "image_save_type")
            layout.prop(context.scene, "export_materials_type")
            layout.prop(context.scene, "compress_folder", icon="FILTER")
            layout.separator()
            layout.operator("export.material_io_export", icon="ZOOMOUT")
                  
        else:
            layout.prop(context.scene, "save_path_import")        
            layout.prop(context.scene, "import_materials_type")
            layout.prop(context.scene, "add_material_auto", icon="MATERIAL")
            layout.separator()       
            layout.operator("import.material_io_import", icon="ZOOMIN")


class MaterialIOExport(bpy.types.Operator):
    bl_idname = "export.material_io_export"
    bl_label = "Export Material"
    
    def execute(self, context):
        export_material(self, context)
        return {"FINISHED"}


class MaterialIOImport(bpy.types.Operator):
    bl_idname = "import.material_io_import"
    bl_label = "Import Material"
    
    def execute(self, context):
        import_material(self, context)
        return {"FINISHED"}             


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
